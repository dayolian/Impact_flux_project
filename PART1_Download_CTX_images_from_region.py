# Script to create clipped subsets of all CTX images in a 
# specified region, corresponding to the pairwise overlaps
# where CTX images intersect.  This should also output a 
# text file delineating the name of each directory created.
# Intended for use as part of the fresh_crater_detection.bat
# pipeline.
#
# Requires ctx downloader.py, CTX_pair_intersections.shp,
# and mars_mro_ctx_edr_c0a.shp to
# be in the present working directory.  Also needs arcpy
# enabled and a working internet connection.
#
# WARNING: This will download many large image files.  Keep
# areas small or be prepared for very long execution times.
#
# Written by Jonathan Sneed, 6-25-2019, in association with
# GALE labs at the UCLA department of Earth, Planetary, and
# Space Sciences.

# UPDATED SEPT 2023 
# Downloads handled via Chrome. Must set chrome default 
# download directory to desired location 

#import selenium
import arcpy
import os
import sys
import csv
import time
from ctx_downloader_rqc import ctx_downloader_rqc 


def clip_ctx_images(ctxId1, ctxId2, polygon):
    delin = "_"
    try:
        results_dir = str(ctxId1) + delin + str(ctxId2) + '\\'
        try:
            os.mkdir(results_dir)
        except OSError as e:
            print(e)
            sys.exit()

        fileb = deep_path + results_dir + str(ctxId1) + delin + str(ctxId2) + delin + 'clippedB.tif' #Before
        filea = deep_path + results_dir + str(ctxId1) + delin + str(ctxId2) + delin + 'clippedA.tif' #After
        
        #Compute step/clip     
        arcpy.Clip_management(ctxId1 + '.tif',
                            '#',
                            fileb,
                            polygon,
                            '0',
                            'ClippingGeometry',
                            'NO_MAINTAIN_EXTENT')

        arcpy.Clip_management(ctxId2 + '.tif',
                            '#',
                            filea,
                            polygon,
                            '0',
                            'ClippingGeometry',
                            'NO_MAINTAIN_EXTENT')

    except Exception as e:
        print(e)
        print('WARNING: Download/Clip accidental termination')
        #os.chdir(direct + '\\' + path)
        return False
    else:
        print('Success: Download/Clip finished.')
        #os.chdir(direct + '\\' + path)
        return True


# Strategy
# NOTE every entry in poly1 is less than poly2

# Loop over all the input area, whole planet or a chunk determined by provided bounds that clip the FIDs down to a relevant area
# Construct 5 main objects/maps
# A: a dictionary with keys representing connectedness (pair participation) mapping to a list of the FIDs that have connectedness of the key
#   0 = [list of pairs]
#   1 = [list of pairs]
# B: a dictionary with FID keys mapping to the connectedness count/value (pair participation) This is reverse lookup of A
#   FID = N
# C: a dictionary with FID keys that map to a list of the connected buddies of the FID
#   FID = [FID, FID2, FID3, FID8]
# D: a dictionary with FID keys that map to the ctxID (or the name of the image) for use as filenames and clipping
#   FID = image_name
# E: a dictionary with a pair key (2 fids that are overlapped) that maps to a polygon object that is used to clip the FIDs in the key
#   (FID1, FID2) = polygon_object

# Main Loop
# Go to A and sort the keys (1 < 2 < 3) and so on
# Start looping over the FIDs that have the lowest connectedness
# Download one (checking if you already have it or if it's "done" already)
# Loop over the appropriate buddies of that FID, checking the same properties
# Download the buddy as needed
# Clip the pair of FID and buddy using the ctxID names
# Check if FID or Buddyare "done"
# delete any that are done
# continue looping over buddies while keeping account of what is downloaded and what pairs have been processed
# once buddies are exhausted return to the top loop of A and keep going
# TODO possible improvement: opportunistically process any downloads that have fewer buddies than the number currently being processed by A
# keep track of how many downloads are currently on the drive, trigger a warning if it goes above N (currently N = 1000)


# This was the whole planet version, swap in the chunk version
#This should be equivalent to
#x1 = -180
#y1 = -90
#x2 = 180
#y2 = -9

#import pandas as pd
#direct = os.path.dirname(os.path.realpath(__file__))
#df = pd.read_csv(direct + '\\' "CTX_pair_intersections_all.csv")
#p1 = pd.unique(df['Polygon1'])
#p2 = pd.unique(df['Polygon2'])


# Variable initializations as needed
x1 = -180
y1 = -75
x2 = -170
y2 = 0
tag = 'Area180S'
#CHANGE CHROME DOWNLOAD PATH!!!!!
#str_x1 = 

# String constructions for file names
direct = os.path.dirname(os.path.realpath(__file__)) #This means: either where the python file is located or where it's executed from
delin = "_"
bounds = delin.join([str(x1), str(x2), str(y1), str(y2)])
path = "output_" + bounds

#TODO consider os.path.join?
fc = path + r'\footprint_clipped_' + tag + '.shp'
#mainRef = direct + '\\' + r'mars_mro_ctx_edr_c0a.shp'
mainRef = os.path.join(direct, 'mars_mro_ctx_edr_c0a.shp') # this is the entire planet

# NO MAKE YOUR OWN DIRECTORY AND SET AS CHROME DOWNLOAD PATH 
# Make a new master directory for the assigned region
# try:
#     os.mkdir(path)
# except OSError as e:
#     print(e)
#     print('Did not make the directory')
#     sys.exit()
# else:
#     print("Successfully created %s" % path)


# Clip overlap shapefile to specified region (cut whole planet down to specific chunk)
try:
    # This is where the starting coordinates are currently initialized
    array = arcpy.Array([arcpy.Point(x1, y1),
                         arcpy.Point(x1, y2),
                         arcpy.Point(x2, y2),
                         arcpy.Point(x2, y1)
                         ])
    polygon = arcpy.Polygon(array)

    arcpy.Clip_analysis('CTX_pair_intersections.shp',polygon, 
                        path + r'\footprint_clipped_' + tag)
except Exception as e:
    print(e)
    print('WARNING: Footprint Clipping terminated without completion.')
    sys.exit()

print('Footprint Clipping phase finished')


counter_dict = {} #this is a map of number, n, to a list of FIDs that have n pair partners #A
pair_participation_dict = {} #this is a mapping for FID to how many pairs the given FID is in #B
pair_connection_map = {} #this is a map of FID to the list of its pair partners. Len() of this is the pair participation value #C
fid_to_ctxid = {} #this is a dictionary of FID to product ID #D
pair_to_polygon = {} #this is a dictionary with a tuple key pair of FIDs mapping to a polygon object (for boundary clipping functionality) #E

unique_poly1 = set()
unique_poly2 = set()
unique_fids = set()

import pandas as pd
direct = os.path.dirname(os.path.realpath(__file__))
#df = pd.read_csv(direct + '\\' + fc) #read the planet subset
#df = pd.DataFrame(columns=['Polygon1', 'Polygon2'])
poly1 = []
poly2 = []

# Construct E and precursors to clipped p1 and p2 (which are the precursors to A, B, C)
# Step through the clipped overlap shapefile, storing all polygons and both associated IDs
try:
    cur = arcpy.da.SearchCursor(fc, ['Polygon1','Polygon2','SHAPE@'])
    for row in cur:
        #print(row)
        pair_to_polygon[(row[0],row[1])] = row[2] #TODO make sure this is a valid thing, and it can return SHAPE@ with the others
        unique_poly1.add(row[0])
        unique_poly2.add(row[1])
        poly1.append(row[0])
        poly2.append(row[1])
        unique_fids.add(row[0])
        unique_fids.add(row[1])
        #df.append('Polygon1'=row[0], 'Polygon2'=row[1])

except Exception as e:
    print(e)
    print('WARNING: CTX library terminated without completion.')
    sys.exit()

poly_dict = {}
poly_dict['Polygon1'] = poly1
poly_dict['Polygon2'] = poly2
df = pd.DataFrame.from_dict(poly_dict)

#print(df)

print('CTX Library phase finished')

#del cur #is this needed?
print('Library phase finished')


#Lazily read the whole planet instead of the chunked thing #does that change if I swap to fc instead of main_rep_pairs?
#Construct D
try:
    #main_ref_pairs is a map of FID to ProductID <- this is the name
    main_ref_pairs = arcpy.da.SearchCursor(mainRef,['FID','ProductID'])
    print('Main ref pairs type', type(main_ref_pairs))
    #If tuple, loop over tuple and make dictionary
    for row in main_ref_pairs:
        fid_to_ctxid[row[0]] = row[1]
except:
    print('Main ref pairs failed to work')
    sys.exit()


# For each polygon: find the CTX IDs/filenames, create a subdirectory, and then
# download both CTX geotiff files to it.  Clip both images to the polygon.
#There is now a pair map and a name map so we can download sets of images

#p1 = unique_poly1
#p2 = unique_poly2


p1 = pd.unique(df['Polygon1'])
p2 = pd.unique(df['Polygon2'])

for entry in p1:
    x = df[(df['Polygon1'] == entry)]
    pair_participation_dict[entry] = len(x)
    pair_connection_map[entry] = list(x['Polygon2'])

for entry2 in p2:
    x = df[(df['Polygon2'] == entry2)]
    if entry2 in pair_participation_dict:
        pair_participation_dict[entry2] += len(x)
    else:
        pair_participation_dict[entry2] = len(x)
    if entry2 in pair_connection_map:
        pair_list = list(x['Polygon1'])
        for pair in pair_list:
            pair_connection_map[entry2].append(pair)
    else:
        pair_connection_map[entry2] = list(x['Polygon1'])

#We now have the full pair connection map and pair participation dict
for key, count in pair_participation_dict.items():
    if count in counter_dict:
        counter_dict[count].append(key)
    else:
        counter_dict[count] = [key]

# Accounting values
avoided_downloads = 0
opportunities = 0
count_above_thresh = 0
total_downloads = 0
current_downloads = 0
downloaded_fids = []
peak_downloads = 0
new_dir_list = []       # Pairs of CTX image names, written to csv for the next step in the process
throttle_counter = 0
throttle_threshold = 600*1000*1000
sleeptime = 310
download_num = 0

print('Main loop begins')
for i in sorted((counter_dict.keys())):
    for dl in downloaded_fids: 
        if pair_participation_dict[dl] < i: #Not implemented
            #run the loop of this one
            #print('Opportunistic option to call the function on a specific fid')
            opportunities += 1
    for fid in counter_dict[i]:
        if not pair_participation_dict[fid]:
            avoided_downloads += 1
            continue
        if fid in downloaded_fids:
            avoided_downloads += 1
            pass
        else:
            #download function
            print('Downloading fid: ', fid)
            deep_path = direct + '\\' + path + '\\'
            os.chdir(deep_path)
            #try:
            #NEW CODE ADDED BY KENZIE Sept2023 TO pass already downloaded IDs
            if os.path.exists(deep_path + '\\' + fid_to_ctxid[fid] + '.tiff'):
                print('CTX image', fid_to_ctxid[fid], ' already downloaded. Passing to next.')
            else:
                ctx_downloader_rqc(fid_to_ctxid[fid])
                #time.sleep(60)
            #except:
            #    print('Failed to download, sleep and try again')
            #    os.remove(fid_to_ctxid[fid] + '.tif')
            #    time.sleep(sleeptime)
            #    ctx_downloader_rqc(fid_to_ctxid[fid])

            


            #sz = os.path.getsize(os.path.join(direct, fid_to_ctxid[fid] + '.tif'))
            # throttle_counter += sz
            # print(throttle_counter/(1000*1000), 'Megabytes in throttle counter')
            # print('i=', i)
            # if throttle_counter > (throttle_threshold):
            #     time.sleep(sleeptime)
            #     print('Throttle threshold hit. Sleeping.......')
            #     throttle_counter = 0


            current_downloads += 1
            downloaded_fids.append(fid)
            total_downloads += 1
            print('Completed download ', total_downloads, ' of ', len(unique_fids))
            
        for fid2 in pair_connection_map[fid]: #these are fids buddies
            if not pair_participation_dict[fid2]:
                avoided_downloads += 1
                continue
            if fid2 in downloaded_fids:
                avoided_downloads += 1
                pass
            else:
                #KENZIE ADDED TO catch duplicate downloads as above 
                if os.path.exists(deep_path + '\\' + fid_to_ctxid[fid2] + '.tiff'):
                    print('CTX image', fid_to_ctxid[fid2], ' already downloaded. Passing to next.')
                else:
                    print('Downloading fid: ', fid2)
                    ctx_downloader_rqc(fid_to_ctxid[fid2])
                #download function
                
                #try: 
                #ctx_downloader_rqc(fid_to_ctxid[fid2])
                #except:
                #    print('Failed to download fid2, sleep and retry')
                #    os.remove(fid_to_ctxid[fid2] + '.tif')
                #    time.sleep(sleeptime)
                #    ctx_downloader_rqc(fid_to_ctxid[fid2])
            
                # sz = os.path.getsize(fid_to_ctxid[fid2] + '.tif')
                # throttle_counter += sz
                # print(throttle_counter/(1000*1000), 'Megabytes in throttle counter')
                # print('i=', i)
                # if throttle_counter > (throttle_threshold):
                #     print('Throttle threshold hit. Sleeping for .......', sleeptime, ' seconds')
                #     time.sleep(sleeptime)
                #     throttle_counter = 0

                current_downloads += 1
                downloaded_fids.append(fid2)
                total_downloads += 1
                print('Completed download ', total_downloads, ' of ', len(unique_fids))
                
            #compute function, clip/etc, whatever you want
            # order matters: lazy way of making sure the order is preserved
            # if fid < fid2:
            #     clipped = clip_ctx_images(fid_to_ctxid[fid], fid_to_ctxid[fid2], pair_to_polygon[(fid, fid2)])
            #     if clipped: #add completed pair to a csv for accounting purposes
            #         new_dir_list.append(str(fid_to_ctxid[fid]))
            #         new_dir_list.append(str(fid_to_ctxid[fid2]))
            # else:
            #     clipped = clip_ctx_images(fid_to_ctxid[fid2], fid_to_ctxid[fid], pair_to_polygon[(fid2, fid)])
            #     if clipped: #add completed pair to a csv for accounting purposes
            #         new_dir_list.append(str(fid_to_ctxid[fid2]))
            #         new_dir_list.append(str(fid_to_ctxid[fid]))
                

            # pair_participation_dict[fid] -= 1
            # pair_participation_dict[fid2] -= 1
            # if not pair_participation_dict[fid]:
            #     if fid in downloaded_fids:
            #         print('Deleting fid: ', fid)
            #         current_downloads -= 1
            #         downloaded_fids.remove(fid)
            #         os.remove(fid_to_ctxid[fid] + '.tif')
            #         #delete/undownload function
                    
            # if not pair_participation_dict[fid2]:
            #     if fid2 in downloaded_fids:
            #         print('Deleting fid: ', fid2)
            #         current_downloads -= 1
            #         downloaded_fids.remove(fid2)
            #         os.remove(fid_to_ctxid[fid2] + '.tif')
            #         #delete/undownload function

            # #Safety Check
            # #if len(downloaded_fids) > 1000:
            # if current_downloads > 1000:
            #     count_above_thresh +=1
            #     #print('AHHHH, I have too many downloaded fids!!!', current_downloads)
            # #freak out and do something
            # if current_downloads > peak_downloads:
            #     peak_downloads = current_downloads

# print('Above threshhold for ', count_above_thresh)
# print('Opportunities available', opportunities)                
# print('Peak Downloads', peak_downloads)
# print('Avoided Downloads', avoided_downloads)
# print('Total Downloads', total_downloads)

# Write .csv containing all downloaded CTX names, so the matlab script knows
# what to align
os.chdir(direct + '\\' + path)

# clipFileName = 'clip_pairs.csv'
# with open(clipFileName,'wb') as pairFile:
#     wr = csv.writer(pairFile)
#     wr.writerow(new_dir_list)

#print('New Pair IDs stored as clip_pairs.csv:')
print('Run complete.')




