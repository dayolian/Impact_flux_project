# Function to provide specified CTX image from PDS.  Scrapes
# asu viewer for supplemental metadata before download.
#
# Written by Jonathan Sneed, 6-15-2019, in association with
# GALE labs at the UCLA department of Earth, Planetary, and
# Space Sciences.

import csv
import os
import sys
import requests
import urllib.request
import webbrowser
import time

def ctx_downloader_rqc(ctxId):

	# Assemble url structure
	ctxurl1 = 'https://image.mars.asu.edu/stream/'
	ctxurl2 = '.tiff?image=/mars/images/ctx/'
	ctxurl3 = '/prj_full/'

	# Retrieve the volume ID from both pages to fill out geotiff url
	fp = urllib.request.urlopen('https://viewer.mars.asu.edu/viewer/ctx/' + ctxId)
	page = fp.read().decode('utf-8')
	idspot = page.find('mrox_')
	volid = page[idspot:idspot+9]
	#Python 2 version
	#fp = urllib.request.urlopen('https://viewer.mars.asu.edu/viewer/ctx/' + ctxId)
	#page = fp.read()
	#idspot = str(page).find('mrox_')
	#volid = str(page)[idspot:idspot+9]

	# Construct URL	
	url = ctxurl1 + ctxId + ctxurl2 + volid + ctxurl3 + ctxId + '.tiff'
	
	# Begin download proper
	print('Dowloading:')
	print(url)

	webbrowser.open(url)
	time.sleep(5)
	# 20 second sleep works well but is slow 