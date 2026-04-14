# UPDATED SEPT 2023 


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
        arcpy.Clip_management(ctxId1 + '.tiff',
                            '#',
                            fileb,
                            polygon,
                            '0',
                            'ClippingGeometry',
                            'NO_MAINTAIN_EXTENT')

        arcpy.Clip_management(ctxId2 + '.tiff',
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

# Variable initializations as needed
x1 = 0
y1 = 0
x2 = 10
y2 = 75
tag = 'Area000N'
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


if os.path.isdir(path):
	print('Folder exists, good to check')
else:
	print('Cant find the folder', path, 'and thus unable to check')
	sys.exit()


# try:
# 	#TODO read the existing shape file
# 	clipped_stuff = arcpy.da.SearchCursor(fc,['Polygon1','Polygon2'])


#     # This is where the starting coordinates are currently initialized
# array = arcpy.Array([arcpy.Point(x1, y1),
#                          arcpy.Point(x1, y2),
#                          arcpy.Point(x2, y2),
#                          arcpy.Point(x2, y1)
#                          ])
#     polygon = arcpy.Polygon(array)

#     arcpy.Clip_analysis('CTX_pair_intersections.shp',polygon, 
#                         path + r'\footprint_clipped_' + tag)


# except Exception as e:
#     print(e)
#     print('WARNING: Footprint Clipping terminated without completion.')
#     sys.exit()
# print('Footprint Clipping phase finished')

if os.path.exists(direct + fc):
	print('Clipped shape file exists already')


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

deep_path = direct + '\\' + path + '\\'
already_downloaded_images = os.listdir(deep_path)

missing_ctxid = []


os.chdir(deep_path)
ctr = 0 #Kenzie added for prog bar 
broken = ['P09_004675_2306_XN_50N111W', 'P09_004675_2233_XN_43N110W', 'P09_004675_2233_XN_43N110W']
for pair, polygon in pair_to_polygon.items():
	ctr += 1		
	print('Clip ', ctr, ' of ', len(pair_to_polygon))
	#if ctr < 586:
	#	continue
	ctx0 = fid_to_ctxid[pair[0]]
	ctx1 = fid_to_ctxid[pair[1]]
	# These cause everything to not clip - don't know why, commenting out 
	#if ctx0 or ctx1 in broken: 
	#	continue
	try: 
		clipped = clip_ctx_images(ctx0, ctx1, polygon)
		new_dir_list.append(str(ctx0))
		new_dir_list.append(str(ctx1))
	except:
		print('Error processing ', ctx0, ' and ', ctx1)
		#continue
	#Kenzie added progress bar: 


#Temp comment out while trblshting
for fid in unique_fids:
	os.remove(fid_to_ctxid[fid] + '.tiff')

os.chdir(direct + '\\' + path)

clipFileName = 'clip_pairs.csv'
with open(clipFileName,'wb') as pairFile:
	wr = csv.writer(pairFile)
	wr.writerow(new_dir_list)

print('New Pair IDs stored as clip_pairs.csv')


# print('Main loop begins')
# for i in sorted((counter_dict.keys())):
#     for dl in downloaded_fids:
#         if pair_participation_dict[dl] < i: #Not implemented
#             #run the loop of this one
#             #print('Opportunistic option to call the function on a specific fid')
#             opportunities += 1
#     for fid in counter_dict[i]:
#         if not pair_participation_dict[fid]:
#             avoided_downloads += 1
#             continue
#         if fid in downloaded_fids:
#             avoided_downloads += 1
#             pass
#         else:
#             #download function
#             #print('Downloading fid: ', fid)
#             #deep_path = direct + '\\' + path + '\\'
#             #os.chdir(deep_path)
#             #try:
#             ctx_id = fid_to_ctxid[fid]
#             if str(ctx_id) + '.tiff' in already_downloaded_images:
#             	print('Already got this one')
#             else:
#             	missing_ctxid.append(ctx_id)



#             	#ctx_downloader_rqc(fid_to_ctxid[fid])
#                 #time.sleep(60)
#             #except:
#             #    print('Failed to download, sleep and try again')
#             #    os.remove(fid_to_ctxid[fid] + '.tif')
#             #    time.sleep(sleeptime)
#             #    ctx_downloader_rqc(fid_to_ctxid[fid])

            


#             #sz = os.path.getsize(os.path.join(direct, fid_to_ctxid[fid] + '.tif'))
#             # throttle_counter += sz
#             # print(throttle_counter/(1000*1000), 'Megabytes in throttle counter')
#             # print('i=', i)
#             # if throttle_counter > (throttle_threshold):
#             #     time.sleep(sleeptime)
#             #     print('Throttle threshold hit. Sleeping.......')
#             #     throttle_counter = 0


#             current_downloads += 1
#             downloaded_fids.append(fid)
#             total_downloads += 1
#             #print('Completed download ', total_downloads, ' of ', len(unique_fids))
            
#         for fid2 in pair_connection_map[fid]: #these are fids buddies
#             if not pair_participation_dict[fid2]:
#                 avoided_downloads += 1
#                 continue
#             if fid2 in downloaded_fids:
#                 avoided_downloads += 1
#                 pass
#             else:
#                 #download function
#                 #print('Downloading fid: ', fid2)
#                 #try: 
#                 ctx_id = fid_to_ctxid[fid2]
#             	if str(ctx_id) + '.tiff' in already_downloaded_images:
#             		print('Already got this one')
#             	else:
#             		missing_ctxid.append(ctx_id)

#                 #ctx_downloader_rqc(fid_to_ctxid[fid2])
#                 #except:
#                 #    print('Failed to download fid2, sleep and retry')
#                 #    os.remove(fid_to_ctxid[fid2] + '.tif')
#                 #    time.sleep(sleeptime)
#                 #    ctx_downloader_rqc(fid_to_ctxid[fid2])
            
#                 # sz = os.path.getsize(fid_to_ctxid[fid2] + '.tif')
#                 # throttle_counter += sz
#                 # print(throttle_counter/(1000*1000), 'Megabytes in throttle counter')
#                 # print('i=', i)
#                 # if throttle_counter > (throttle_threshold):
#                 #     print('Throttle threshold hit. Sleeping for .......', sleeptime, ' seconds')
#                 #     time.sleep(sleeptime)
#                 #     throttle_counter = 0

#                 current_downloads += 1
#                 downloaded_fids.append(fid2)
#                 total_downloads += 1