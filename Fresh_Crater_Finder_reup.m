% Script for identifying candidate fresh craters from clipped CTX images
% Summer 2022
% Updated March 2025

close all; clear all; clc; warning('off')
%
% %Load in the pre-tuned refence surface to compare region properties against
% %region properties of known fresh craters in CTX. See
% %calibration_tuning_FINAL.m for generation of this surface
% load('impact_reference.mat')

% Code to iterate through all folders courtesy of chatGPT
% Define the main directory containing all folders
mainDir = 'G:\crater_flux_output_folders';

% Define log file path
logFile = fullfile(mainDir, 'error_log.txt');

% Open log file in append mode
logID = fopen(logFile, 'a');

% Get a list of all folders in the main directory
folders = dir(mainDir);
folders = folders([folders.isdir]); % Keep only directories
folders = folders(~ismember({folders.name}, {'.', '..'})); % Remove '.' and '..'

% Filter only folders starting with "output"
folders = folders(startsWith({folders.name}, 'output')) % For MATLAB R2016b+


% Loop through each folder and run your existing script
for k = 1:length(folders)
    folderPath = fullfile(mainDir, folders(k).name);
    fprintf('Processing folder: %s\n', folderPath);

    % Change directory to the current folder
    cd(folderPath);

    % Call your existing MATLAB script or function
    try

        clearvars -except k folderPath folders mainDir logID

        %Load in the pre-tuned refence surface to compare region properties against
        %region properties of known fresh craters in CTX. See
        %calibration_tuning_FINAL.m for generation of this surface
        load([mainDir '\' 'impact_reference.mat'])

        %cd 'G:\crater_flux_output_folders\output_-115_-110_-15_-10\'

        [~,pair_list,~] = xlsread('clip_pairs.csv');

        counter = 0;
        corscor = zeros(length(pair_list),1);
        dims = zeros(length(pair_list),2);
        regs = zeros(length(pair_list),1);
        hits = zeros(length(pair_list),1);

        pl1 = '';
        pl2 = '';

        tic

        for i = 1:2:length(pair_list)

            try
                %% SETUP CTX IMAGE PAIR
                pl1 = pair_list{i};
                pl2 = pair_list{i+1};
                name_root = [pl1,'_',pl2];
                cd([folderPath '\' name_root])

                if exist('candidates_t.mat', 'file')
                    fprintf('Skipping folder (candidates_t.mat found): %s\n', name_root)
                    cd ..
                    continue
                end

                ctx1 = [name_root,'_clippedB.tif'];
                ctx2 = [name_root,'_clippedA.tif'];
                ctxID = name_root;

                disp(ctx1)
                disp(['Image pair ' num2str((i+1)/2) ' of ' num2str(length(pair_list)/2)])

                %% LOAD, PROCESS, ALIGN IMAGES
                % Read in both (b)efore and (a)fter images, as well as the bounding polygon
                % (for later buffering).  Assumes current working directory.
                [Ab,Rb] = geotiffread(ctx1);
                [Aa,Ra] = geotiffread(ctx2);

                bx = mean(Rb.XWorldLimits);
                by = mean(Rb.YWorldLimits);

                % Data hygiene- make sure Arc's formats make sense
                Ab = uint8(Ab);
                Aa = uint8(Aa);

                % Trial reversal of NaNs
                Ab(Ab == 0) = NaN;
                Aa(Aa == 0) = NaN;
                Ab(Ab == 255) = NaN;
                Aa(Aa == 255) = NaN;

                %data type hygiene step
                Ab = int16(Ab);
                Aa = int16(Aa);

                %Normalization and contrast stretching
                Arange = (prctile(Aa,95,'all') - prctile(Aa,5,'all'));
                Brange = (prctile(Ab,95,'all') - prctile(Ab,5,'all'));
                contRatio = double(Brange)/double(Arange);
                Ad = Aa - prctile(Aa,5,'all');
                Ad = Ad * contRatio + prctile(Ab,5,'all');
                Ad = Ad + (mean(mean(mean(Ab))) - mean(mean(mean(Ad))));

                %data type hygiene step
                Ab = uint8(Ab);
                Aa = uint8(Aa);
                Ad = uint8(Ad);

                % Alignment step: translation only alignment
                scale = 15; %(amount of downsample in image registration)
                [tformEst, score] = imregcorr(imresize(Ad, 1/scale), imresize(Ab, 1/scale), 'translation');
                % Add a test for if score low (bad registration)
                tformEst.T(3,1:2) = tformEst.T(3,1:2).*scale;
                Rf = imref2d(size(Ab));
                Ad = imwarp(Ad,tformEst,'OutputView',Rf);

                %% CREATE BINARY MAP

                % Tuned pruning parameters
                % For tuning info see 'calibration_tuning_FINAL.m'
                % Difference threshold
                dt = 0.35;

                % Minimum area
                ma = 35;

                % Get logical difference map of oriented images, indicating difference
                % values over the threshold.  Buffer along the way.
                B = double(Ab)./double(max(max(Ab)));
                D = double(Ad)./double(max(max(Ad)));
                BDdiff = sqrt((B - D).^2);

                % Second pass - smooth, square, and then filter
                window_size = 5;
                wind = ones(window_size, window_size)./(window_size^2);
                BDdiff_smoothed = conv2(BDdiff.^2, wind, 'same');

                BDL0 = logical(BDdiff_smoothed > dt.^2);

                BDL = bwareafilt(BDL0,[ma,12000]);% Max area of 12k px set by max area of known impacts (11.3k px)

                %% REGION PROPERTIES
                % Assess properties of contiguous above threshold pixels
                stats = regionprops(BDL,...
                    'centroid',...
                    'area',...
                    'perimeter',...
                    'eccentricity',...
                    'convexarea', 'eulernumber');
                statsM1 = [cat(1,stats.Centroid),...
                    cat(1,stats.Area),...
                    cat(1,stats.Perimeter),...
                    cat(1,stats.Eccentricity),...
                    cat(1,stats.ConvexArea),...
                    cat(1,stats.EulerNumber)];

                if isempty(stats)
                    cd ..
                    clearvars -except k folderPath folders mainDir logID pair_list i xgrid ygrid zgrid elngrid counter corscor dims regs hits
                    continue
                end

                % Find object stats
                LOC = statsM1(:,1:2);
                ARE = statsM1(:,3);
                PAR = (4.*pi.*ARE)./statsM1(:,4).^2;
                ECC = statsM1(:,5);
                CVA = statsM1(:,3) ./ statsM1(:,6);
                ELN = statsM1(:,7);

                %% COMPARE REGION PROPS WITH REFERENCE SURFACE
                %Analyze the region properties in the 3 dimensional space defined by
                %PAR, ECC, CVA (X Y Z). Also check ELN later.

                % First interpolate the PAR and ECC data to the reference grids
                % (i.e., what value does the reference surface have at the given
                % points? Do this separately for CVA and ENL to avoind 4D matrix and
                % give separate emphasis)

                CVA_ref = interp2(xgrid, ygrid, zgrid, PAR, ECC);
                ELN_ref = interp2(xgrid, ygrid, elngrid, PAR, ECC);

                Cnan = isnan(CVA_ref); %Regions outside the defined calibration area
                above = CVA>CVA_ref & CVA<1; %Regions above the threshold surface (convex hull); CVA must also not equal 1)
                elnchk = ELN>=ELN_ref-3; %Regions above the threshold surface, including a buffer of 3 (holes)
                dblchk = above & elnchk; %Regions that pass both CVA and ELN checks (CVA much stronger filter)

                %% REMOVE HITS FROM EDGE OF IMAGES
                % Because the overlap/clipping/shapefiles are imperfect, some detections
                % concentrate along the edges of the overlapping images. Check whether the
                % potential fresh crater is centeres on an all black 11x11px square in
                % either image

                %Start with hits that pass both checks

                LOC_dbl = LOC(dblchk,:);
                box_size = 5;%Size of window checked in images = 2*window+1
                edge_remover = ones(length(LOC_dbl(:,1)), 1);
                [h, w] = size(Ab);
                for j = 1:length(LOC_dbl(:,1))
                    row = round(LOC_dbl(j,2));
                    col = round(LOC_dbl(j,1));
                    image_edge = [(row-5)<=0, (row+5)>h, (col-5)<=0, (col+5)>w];
                    if any(image_edge)
                        edge_remover(j)=0;
                        continue
                    end
                    Ab_val = mean(mean((Ab(row-5:row+5, col-5:col+5))));
                    Ad_val = mean(mean((Ad(row-5:row+5, col-5:col+5))));
                    if Ab_val == 0 | Ad_val == 0
                        edge_remover(j)=0;
                    end
                end


                %% PULL OUT ABOVE THRESHOLD, NON_EDGE DATA
                ARE_dbl = ARE(dblchk);
                PAR_dbl = PAR(dblchk);
                ECC_dbl = ECC(dblchk);
                CVA_dbl = CVA(dblchk);

                edge_remover = logical(edge_remover);
                LOC_pass = LOC_dbl(edge_remover,:);
                ARE_pass = ARE_dbl(edge_remover);
                PAR_pass = PAR_dbl(edge_remover);
                ECC_pass = ECC_dbl(edge_remover);
                CVA_pass = CVA_dbl(edge_remover);

                %% DISPLAY DATA FOR TRBLSHT

                % disp(['Total regions: ' num2str(length(PAR))])
                % disp(['Image dimensions: ' num2str(size(Ad))])
                % %     disp(['Total outside zone: ' num2str(sum(Cnan))])
                % %     disp(['Total under surface: ' num2str(length(CVA_ref)-sum(Cnan)-sum(above))])
                % %     disp(['Total above surface (check1): ' num2str(sum(above))])
                % disp(['Total above surface and Euler Num (check2): ' num2str(sum(dblchk))])
                disp(['Total triple checked hits: ' num2str(length(ARE_pass))])
                % More visuals
                %figure,imshow(BDL); hold on; plot(LOC_pass(:,1), LOC_pass(:,2), 'r*')
                %figure, imshow(BDdiff_smoothed); hold on; plot(LOC_pass(:,1), LOC_pass(:,2), 'r*')


                % Save potential fresh crater metadata for later reference
                save candidates_t.mat ctxID bx by LOC_pass ARE_pass PAR_pass ECC_pass CVA_pass

                counter = counter+length(ARE_pass);
                corscor(i) = score;
                dims(i,:) = size(Ad);
                regs(i) = length(PAR);
                hits(i) = length(ARE_pass);

                cd ..



            catch MC
                fprintf('Error processing subfolder %s: %s\n', name_root, MC.message);
                % Write to log file
                fprintf(logID, 'Error in subfolder: %s\nError Message: %s\n\n', [folderPath '\' name_root], MC.message);

            end
        end
        disp(['All pairs completed. ' num2str(counter) ' potenital hits from this folder'])
        toc


    catch ME
        fprintf('Error processing high-level folder %s: %s\n', folderPath, ME.message);
        % Write to log file
        fprintf(logID, 'Error in high-level folder: %s\nError Message: %s\n\n', folderPath, ME.message);
    end
end

% Close the log file
fclose(logID);

% Return to the main directory
cd(mainDir);

alldone = fullfile(mainDir, 'script_done.txt'); 
doneID = fopen(alldone, 'a')
fclose(doneID)
