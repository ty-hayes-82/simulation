#import modules
from datetime import datetime, date, timedelta
import urllib.parse
import os, subprocess
import sys
import pyodbc
import pandas as pd
import email
import smtplib
from email.mime.application import MIMEApplication
#from email.message import EmailMessage
from email.utils import make_msgid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

def hour_rounder(t):
    return (t.replace(second=0, microsecond=0, minute=0, hour=t.hour)
               +timedelta(hours=t.minute//30))

#Initialize Generic Variables
report_date = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
report_date_time = hour_rounder(datetime.now()).strftime("%m-%d-%Y %H%M")
email_date = (date.today() - timedelta(days=1)).strftime('%m-%d-%Y')
dir_path = '//swift.com/shared_data/Reports/Tableau Reports/'
python_script_path = '/Users/Public/Documents/Python_Scripts/Capacity_Forecast/'
path = dir_path + report_date

#Initialize Report Specific Variables
#recipients = ['tableauotrnetbal@swifttrans.com','linehaulplanningleaders@SwiftTrans.onmicrosoft.com','ty_hayes@swifttrans.com', 'ruthie_young@swifttrans.com','christopher.makaila@knighttrans.com']
recipients = ['ty_hayes@swifttrans.com']

if datetime.now().hour == 5:
    recipients.append("andrew_hess@swifttrans.com")
#recipients = ['ty_hayes@swifttrans.com','ruthie_young@swifttran.com']
from_email = 'reports@swifttrans.com'
temp_folder_path = '//swift.com/shared_data/Reports/Tableau Reports/tempCapacityForecast'
file_type_list = ['png','pdf']
tb_report_name = 'Capacity Forecast'

# Swift site configuration
tb_wb_path = 'views/CapacityForecast_16581581862420'
tb_view_path = 'views/CapacityForecast_16581581862420/_CapacityForecastMap'
tb_hyperlink_path = 'https://tableau.swift.com/#/site/Swift/views/CapacityForecastandCsrPace'
tableau_view_list_1 = ['NetBal-Today','NetBal-TodayTomorrow']

# KNX site configuration
knx_view_path = 'views/SwiftForecastKMASubscription/SwiftForecastKMASubscription'
knx_hyperlink_path = 'https://tableau.swift.com/#/site/KNX/views/SwiftForecastKMASubscription/SwiftForecastKMASubscription'
knx_view_name = 'SwiftForecastKMASubscription'


#create temp_folder_path folder where daily lob reports are stored (delete current contents first)
import shutil
os.chdir(dir_path)
if not os.path.exists(temp_folder_path):
    os.makedirs(temp_folder_path)

#Create folder with report_date's date if they don't already exist
if not os.path.exists(path):
    os.makedirs(path)

outF = open(r"C:" + python_script_path + tb_report_name + ".bat","w")

# Login to Swift site
outF.write(r"""tabcmd login -s ndctableaup11 -u svc_tableau_prod -p 65GC(HcQ!nM3 --no-certcheck""")
outF.write("\n")

# Generate Swift site views
for typ in file_type_list:
    part1 = 'tabcmd get "' + tb_view_path + '.' + typ + '?:refresh=yes'
    part2 = '" -t Swift -f "' + temp_folder_path + '/'
    part3 = '.' + typ + '" -p 65GC(HcQ!nM3  --no-certcheck'
    for line in tableau_view_list_1:
        outF.write('tabcmd get "' + tb_wb_path + '/_' + line + '.' + typ + '?:refresh=yes' + part2 + line + part3)
        outF.write("\n")

# Login to KNX site
outF.write("echo Logging into KNX site...\n")
outF.write(r"""tabcmd login -s ndctableaup11 -u svc_tableau_prod -p 65GC(HcQ!nM3 --no-certcheck""")
outF.write("\n")
outF.write("echo KNX login completed, starting view downloads...\n")

# Generate KNX site view (no filters, just once)
for typ in file_type_list:
    knx_part2 = '" -t KNX -f "' + temp_folder_path + '/'
    knx_part3 = '.' + typ + '" -p 65GC(HcQ!nM3  --no-certcheck'
    outF.write('echo Downloading KNX view: ' + knx_view_name + '.' + typ + '\n')
    outF.write('tabcmd get "' + knx_view_path + '.' + typ + '?:refresh=yes' + knx_part2 + knx_view_name + knx_part3)
    outF.write("\n")

outF.write("echo All downloads completed.\n")

outF.close()

#Start tabcmd
subprocess.call(r"C:" + python_script_path + tb_report_name + ".bat")

#Merge PDFs into One File
from PyPDF2 import PdfFileMerger, PdfFileReader
merger = PdfFileMerger()
os.chdir(temp_folder_path)

for line in tableau_view_list_1:
    for f in os.listdir():
        if f.startswith(line):
            if f.endswith(line + ".pdf"):
                merger.append(PdfFileReader(f), line)

# Add KNX view to PDF merger
for f in os.listdir():
    if f.startswith(knx_view_name):
        if f.endswith(knx_view_name + ".pdf"):
            merger.append(PdfFileReader(f), knx_view_name)

#Create folder with report_date's date if they don't already exist
if not os.path.exists(path):
    os.makedirs(path)

merger.write(path + '/' + tb_report_name + ' - ' + report_date_time + '.pdf')

#Get username and password from Email_Credentials.txt file
f = open(r"C:\Users\Public\Documents\Python_Scripts\Email_Credentials.txt","r")
lines = f.readlines()
usr = lines[0].strip()
psswrd = lines[1].strip()
f.close()

#msg = EmailMessage()
msg = MIMEMultipart('related')
msg['Subject'] = 'Linehaul OTR 10 Day Capacity Forecast'
msg['From'] = from_email
msg['To'] = ", ".join(recipients)

msg.preamble = 'This is a multi-part message in MIME format.'

msgAlternative = MIMEMultipart('alternative')
msg.attach(msgAlternative)
msgText = '<html><p style="font-family: Verdana; font-size:20px">Linehaul OTR 10 Day Capacity Forecast</p><body>'
for line in tableau_view_list_1:
    for f in os.listdir():
        if f.startswith(line):
            if f.endswith(line + ".png"):
                image_cid = make_msgid()
                msgText += '<a href="' + tb_hyperlink_path + '/' + line + '"><img src="cid:{image_cid}"><br>'.format(image_cid=image_cid[1:-1])
                with open(f, 'rb') as f:
                    msgImage = MIMEImage(f.read())
                msgImage.add_header('Content-ID', image_cid)
                msg.attach(msgImage)
# Add KNX view to email
for f in os.listdir():
    if f.startswith(knx_view_name):
        if f.endswith(knx_view_name + ".png"):
            image_cid = make_msgid()
            msgText += '<a href="' + knx_hyperlink_path + '"><img src="cid:{image_cid}"><br>'.format(image_cid=image_cid[1:-1])
            with open(f, 'rb') as f:
                msgImage = MIMEImage(f.read())
            msgImage.add_header('Content-ID', image_cid)
            msg.attach(msgImage)
msgText += '</body>'
msgText += '<p>CONFIDENTIALITY NOTICE: This e-mail, including any attachments, is for the sole use of the intended recipient(s) and may contain confidential and privileged information. Any unauthorized review, use or disclosure is prohibited. If you are not the intended recipient, please contact the sender immediately and destroy all copies of the original message.</p>'
msgText += '</html>'
msgAlternative.attach(MIMEText(msgText, 'html'))

#Get pdf files from os.chdir(path)
os.chdir(path)
filename= tb_report_name + ' - ' + report_date_time + '.pdf'
fo=open(filename,"rb")
attach = email.mime.application.MIMEApplication(fo.read(),_subtype="pdf")
fo.close()
attach.add_header("Content-Disposition","attachment",filename=filename)
msg.attach(attach)

with smtplib.SMTP("mailrelay.swifttrans.com", 25) as server:
    server.sendmail(msg['From'], recipients,  msg.as_string())

if os.path.exists(temp_folder_path):
    shutil.rmtree(temp_folder_path)
