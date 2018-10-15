#! /usr/bin/python
"""Script to check users in healthcare exclusion lists

This checks the following sources:
    * SAM exclusion list
    * OIG Exclusion list
    * OFAC list of Specially Designated Nationals and Blocked Persons (SDN)
    * FDA Clinical Investigations Disqualification Proceedings
    * FDA Debarment List (Drug Product Applications)
    * TRICARE Sanctioned Providers

Dependencies:
    * requests (http://docs.python-requests.org/)
    * beautifulsoup4 (http://www.crummy.com/software/BeautifulSoup/bs4/doc/)
"""

# ----------------------------------------------------------------------------
#  The list of people to check
# ----------------------------------------------------------------------------

# A list of individuals to match. Note, the examples here will cause matches
individuals = []
'''   # In: SAM, OIG
    {
        'first': 'Nathan',
        'last': 'Pack',
    },
    # In: SAM, OIG. O, and absolutely no relation to the author. =)
    {
        'first': 'Douglas',
        'last': 'Schmid',
    },
    # In: SAM, SDN
'''
# ----------------------------------------------------------------------------
# Don't modify anything below... unless you know what you're doing
# ----------------------------------------------------------------------------

from collections import defaultdict
import copy
import csv
import tempfile
import zipfile
import argparse

import bs4
import requests


class OFACReader(object):
    """Reader for the OFAC SDN list file"""

    def __init__(self, f):
        self.f = f
        self.dialect = 'OFAC'
        self.line_num = 0
        
        # Read the header lines
        self.header = u''
        n_spaces = 2
        while n_spaces >= 0:
            line = f.readline().strip()
            self.line_num += 1
            if line.strip() == u'':
                n_spaces -= 1
                line = u'\n'
            self.header += line
        self.header = self.header.strip()

    def next(self):
        retval = ''
        try:
            for l in f:
                stripped = l.strip()
                self.line_num += 1
                if stripped:
                    retval += stripped
                else:
                    yield retval
                    retval = u''
        except StopIteration:
            if retval is not None:
                yield retval
            else:
                raise StopIteration

    def __iter__(self):
        return self.next()


class FDADebarmentReader(object):
    """Reader for the FDA Debarment List (Drug Product Applications)"""

    def __init__(self, html):
        self.html = html

    def next(self):
        # Only get the second table since the first one is for firms
        table = self.html.find_all('table')[1]
        rows = table.find('tbody').find_all('tr')
        for row in rows:
            # Split the row into it's parts
            # Name, Effective Date, End Date, FR Date, Volume Page
            cells = [cell.text for cell in row.find_all('td')]
            cells[0] = cells[0].replace(u"*", "")
            if cells[0].strip() == "":
                continue
            yield {
                'Name':             cells[0],
                'Effective Date':   cells[1],
                'End Date':         cells[2],
                'FR Date':          cells[3],
                'Volume Page':      cells[4],
            }

    def __iter__(self):
        return self.next()


class TRICAREReader(object):
    """Reader for the US Military TRICARE Sanction List"""
    def __init__(self, html):
        self.html = html

    def next(self):
        items = html.find_all('section')
        for item in items:
            yield {dt.text.replace(':', ''): dt.findNext('dd').text
                   for dt in item.find_all('dt')}

    def __iter__(self):
        return self.next()

def download(url, f, tls_v1=False):
    """Download the file a the given URL to file f"""
    try:
        r = requests.get(url, stream=True)
    except:
        print "If this is not working for you, please install the following: "
        print "    pip install pyopenssl"
        print "    pip install requests[security]"
        print "For details see: https://github.com/kennethreitz/requests/issues/2906"
        raise
    for chunk in r.iter_content(chunk_size=1024): 
        if chunk:
            f.write(chunk)
    f.seek(0)
    return f



with open('empl_census.csv') as csvfile:
    csvReader=csv.reader(csvfile,delimiter=',',quotechar='"')
    header = csvReader.next()
    for row in csvReader:
        individuals.append({'first': row[1],'last': row[0]})

#
# Make all the individual names lower case for easier matching later
#
for individual in individuals:
    for k, v in individual.iteritems():
        individual[k] = v.lower()


# A place to put all of the matches
matches = defaultdict(list)

# 
# Check the data from the SAM exclusion list
# https://www.sam.gov/public-extracts/SAM-Public/SAM_Exclusions_Public_Extract.ZIP
#

print
print "Checking the following list of people:"
print "--------------------------------------"
for individual in individuals:
    print u"{} {}".format(individual['first'], individual['last']).title()
print "--------------------------------------"
print

print "Checking SAM exclusion list..."
with tempfile.TemporaryFile() as f:

    download(
        "https://www.sam.gov/public-extracts/SAM-Public/SAM_Exclusions_Public_Extract.ZIP",
        f,
        tls_v1=True)
    
    with zipfile.ZipFile(f, 'r') as zipf:

        reader = csv.DictReader(
            zipf.open(zipf.namelist()[0]),
            fieldnames=[
                "Classification","Name","Prefix","First","Middle","Last","Suffix",
                "Address 1","Address 2","Address 3","Address 4","City",
                "State / Province","Country","Zip Code","DUNS","Exclusion Program",
                "Excluding Agency","CT Code","Exclusion Type",
                "Additional Comments","Active Date","Termination Date",
                "Record Status","Cross-Reference","SAM Number","CAGE","NPI"])
        for l in reader:
            for individual in individuals:
                if (l['First'].lower() == individual['first'] and
                        l['Last'].lower() == individual['last']):
                    matches["SAM"].append(
                        (individual, copy.deepcopy(l))
                    )
                    continue                    

#
# Check the data from OIG Exclusion list
# http://oig.hhs.gov/exclusions/downloadables/updatedleie.txt
#

print "Checking OIG exclusion list..."
with tempfile.TemporaryFile() as f:
    
    #download("https://oig.hhs.gov/exclusions/downloadables/updatedleie.txt", f)
    download("https://oig.hhs.gov/exclusions/downloadables/UPDATED.csv", f)

    reader = csv.DictReader(
        f,
        fieldnames=[
            "LASTNAME","FIRSTNAME","MIDNAME","BUSNAME","GENERAL","SPECIALTY",
            "UPIN","NPI","DOB","ADDRESS","CITY","STATE","ZIP","EXCLTYPE",
            "EXCLDATE","REINDATE","WAIVERDATE","WVRSTATE"])
    for l in reader:
        for individual in individuals:
            first_name = l['FIRSTNAME'] or ""
            last_name = l['LASTNAME'] or ""
            if (first_name.lower() == individual['first'].lower() and
                    last_name.lower() == individual['last']):
                matches["OIG"].append(
                    (individual, copy.deepcopy(l))
                )

#
# Check the OFAC list
# https://www.treasury.gov/ofac/downloads/sdnlist.txt
#

print "Checking OFAC SDN list..."
with tempfile.TemporaryFile() as f:

    download("https://www.treasury.gov/ofac/downloads/sdnlist.txt", f)

    reader = OFACReader(f)
    for l in reader:
        for individual in individuals:
            if (individual['first'] in l.lower()
                    and individual['last'] in l.lower()):
                matches["SDN"].append(
                    (individual, copy.deepcopy(l))
                )

#
# Check the FDA Disqualification list
# http://www.accessdata.fda.gov/scripts/SDA/sdExportData.cfm?sd=clinicalinvestigatorsdisqualificationproceedings&exportType=csv
#

print "Checking FDA Disqualification list..."
with tempfile.TemporaryFile() as f:

    download("http://www.accessdata.fda.gov/scripts/SDA/sdExportData.cfm?sd=clinicalinvestigatorsdisqualificationproceedings&exportType=csv", f)

    reader = csv.DictReader(
        f,
        fieldnames=[
            "Name", "Center", "City", "State", "Status", "Date of status",
            "Date NIDPOE Issued", "Date NOOH Issued", "Link to NIDPOE Letter",
            "Link to NOOH Letter", "Date of Presiding Officer Report",
            "Link to Presiding Officer Report", "Date of Commissioner's Decision",
            "Link to Commissioner's Decision"])
    for l in reader:
        for individual in individuals:
            if (individual['first'] in l['Name'].lower()
                    and individual['last'] in l['Name'].lower()):
                matches["FDA-Disqualification"].append(
                    (individual, copy.deepcopy(l))
                )

#
# Check the FDA Debarment List (Drug Product Applications)
# http://www.fda.gov/ICECI/EnforcementActions/FDADebarmentList/default.htm 
#

print "Checking FDA Debarment List (Drug Product Applications)..."
r = requests.get('http://www.fda.gov/ICECI/EnforcementActions/FDADebarmentList/default.htm')
html = bs4.BeautifulSoup(r.text)
for l in FDADebarmentReader(html):
    for individual in individuals:
        if (individual['first'] in l['Name'].lower()
                and individual['last'] in l['Name'].lower()):
            matches["FDA-Debarment"].append(
                (individual, copy.deepcopy(l))
            )
 
#
# Check the TRICARE data from health.mil
# http://www.health.mil/Military-Health-Topics/Access-Cost-Quality-and-Safety/Quality-And-Safety-of-Healthcare/Program-Integrity/Sanctioned-Providers
#
# Note: Unfortunately they aren't nice enough to have a nice download
# and/or an easy to access set of data. But that's not a problem. =)
#

print "Checking TRICARE Sanction List..."

tricare_url = "http://www.health.mil/Military-Health-Topics/Access-Cost-Quality-and-Safety/Quality-And-Safety-of-Healthcare/Program-Integrity/Sanctioned-Providers"

# Do a GET on the page to get the cookie and session ID and such
r = requests.get(tricare_url)

form_data = {
    'ctl01$txtSearch': "",
    'pagecolumns_0$content_2$txtName': "",
    'pagecolumns_0$content_2$ddlCountry': "{D37DF6CE-B49A-469C-BA45-2A6E758EF1AD}",
    'pagecolumns_0$content_2$txtCity': "",
    'pagecolumns_0$content_2$ddlState': "",
    'pagecolumns_0$content_2$btnViewAll': "View All",
    '__EVENTTARGET': "",
    '__EVENTARGUMENT': ""
}
html = bs4.BeautifulSoup(r.text)
for key in ('__EVENTVALIDATION', '__VIEWSTATE', '__VIEWSTATEGENERATOR', '__EVENTVALIDATION'):
    form_data[key] = html.find('input', {'id': key}).get('value')

# POST the form with all of the appropriate data
r = requests.post(
    tricare_url,
    data=form_data,
    cookies=r.cookies)

html = bs4.BeautifulSoup(r.text)
for l in TRICAREReader(html):
    if not l.get('People'):
        continue
    for individual in individuals:
        if (individual['first'] in l['People'].lower()
                and individual['last'] in l['People'].lower()):
            matches["TRICARE"].append(
                (individual, copy.deepcopy(l))
            )


#
# Aaaaand, we're done.
#

if matches:
    print "The following matches were found:"
    print
    for kind, individuals in matches.iteritems():
        print
        print "=" * 80
        print "=", kind
        print "=" * 80
        for individual in individuals:
            print individual
else:
    print "No matches found"
