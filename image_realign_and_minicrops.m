% Image re-align and clip out 100x100 jpegs for GUI serving

% Mackenzie Day
% March 2025
% Updated March 2026

% Print info and save graphic about hit ratio distribition
% ~13M hits = ~26M images @4KB/image ~~ 100 GB

close all; clear all; clc;

%% SETUP, LOADING, AND LOGGING
mainDir = 'G:\crater_flux_output_folders';
masterFile = fullfile(mainDir, 'pairsinfo_with_tformscore.csv');
data = readtable(masterFile, 'Delimiter', ',');

% Define log file path
logFile = fullfile(mainDir, 'alignment_error_log_Winter2026.txt');

% Open log file in append mode
logID = fopen(logFile, 'a');

% Iterate through each row in the table
for i = 101250:height(data) %CHANGE BACK TO 1!!!! DID 64164to skip ahead in DEBUGGING
    clearvars -except i mainDir logID logFile data
    % Extract path, ctxid, and hits
    folderPath = data{i, 1}{1};  % The folder path as a string
    ctxid = data{i, 2}{1};       % The ctxid string

    if data.RegistrationScore(i)>0
        fprintf('Already processed %s. Skipping.\n', ctxid);
        continue
    end

    % Display progress
    fprintf('Processing entry %d of %d: %s\n', i, height(data), ctxid);

    % Construct the full paths to the before and after images
    before_image_path = fullfile(folderPath, [ctxid, '_clippedB.tif']);
    after_image_path = fullfile(folderPath, [ctxid, '_clippedA.tif']);

    % Check if the image files exist
    if ~isfile(before_image_path) || ~isfile(after_image_path)
        fprintf('Missing files for %s. Skipping.\n', ctxid);
        continue;
    end
    %% LOAD, PROCESS, ALIGN IMAGES
    try

        % Read in both (b)efore and (a)fter images, as well as the bounding polygon
        % (for later buffering).  Assumes current working directory.
        [Ab,Rb] = geotiffread(before_image_path);
        [Aa,Ra] = geotiffread(after_image_path);

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

        data.RegistrationScore(i) = score;

        if i==101295 %mod(i, 50) == 0   DEBUGGING
            fprintf('.................Saving table................. \n');
            writetable(data, 'pairsinfo_with_tformscore.csv');
        end


        %% Load candidates_t.mat and crop jpegs
        mat_file = fullfile(folderPath, 'candidates_t.mat');
        if isfile(mat_file)
            load(mat_file, 'LOC_pass', 'ARE_pass');  % Load LOC_pass variable
        else
            fprintf('Missing candidates_t.mat file in %s. Skipping.\n', folderPath);
            continue;
        end

        % Process each potential crater location in LOC_pass
        for j = 1:size(LOC_pass, 1)
            % Get the (x, y) coordinates
            imx = LOC_pass(j, 1);
            imy = LOC_pass(j, 2);

            % Convert to integer pixels
            x = round(imx);
            y = round(imy);

            crop_size = 100;
            half_size = crop_size/2;

            % Define cropping area
            x_min = x - half_size + 1;
            x_max = x + half_size;
            y_min = y - half_size + 1;
            y_max = y + half_size;

            % Crop the regions from both images (using size() directly)
            crop_before = Ab(max(1, y_min):min(size(Ab, 1), y_max), max(1, x_min):min(size(Ab, 2), x_max));
            crop_after = Ad(max(1, y_min):min(size(Ad, 1), y_max), max(1, x_min):min(size(Ad, 2), x_max));

            % Get current crop size
            [crop_h, crop_w] = size(crop_before);
            [crop_ha, crop_wa] = size(crop_after);

            % If the crop is smaller than 100x100, we need to pad it
            if crop_h < crop_size || crop_w < crop_size
                % Calculate padding needed
                pad_top = max(0, half_size - (y - 1));
                pad_bottom = max(0, half_size - (size(Ab, 1) - y));
                pad_left = max(0, half_size - (x - 1));
                pad_right = max(0, half_size - (size(Ab, 2) - x));

                % Apply padding to the cropped images
                crop_before = padarray(crop_before, [pad_top, pad_left], 0, 'pre');
                crop_before = padarray(crop_before, [pad_bottom, pad_right], 0, 'post');

            elseif crop_ha < crop_size || crop_wa < crop_size
                % Calculate padding needed
                pad_top = max(0, half_size - (y - 1));
                pad_bottom = max(0, half_size - (size(Ad, 1) - y));
                pad_left = max(0, half_size - (x - 1));
                pad_right = max(0, half_size - (size(Ad, 2) - x));

                % Apply padding to the cropped image (after)
                crop_after = padarray(crop_after, [pad_top, pad_left], 0, 'pre');
                crop_after = padarray(crop_after, [pad_bottom, pad_right], 0, 'post');
            end

            % Save the crops as JPEGs
            before_jpeg_path = fullfile(folderPath, sprintf('hit_%d_%d_%d_before.jpg', ARE_pass(j), x, y));
            after_jpeg_path = fullfile(folderPath, sprintf('hit_%d_%d_%d_after.jpg', ARE_pass(j), x, y));
            %unadjusted_jpeg_path = fullfile(folderPath, sprintf('hit_%d_%d_unadjusted.jpg', x, y));


            imwrite(crop_before, before_jpeg_path, 'Quality', 80);
            imwrite(crop_after, after_jpeg_path, 'Quality', 80);
            %imwrite(crop_unadjusted, unadjusted_jpeg_path, 'Quality', 80);

        end

    catch MC
        fprintf('Error processing subfolder %s: %s\n', folderPath, MC.message);
        % Write to log file
        fprintf(logID, 'Error in subfolder: %s\nError Message: %s\n\n', folderPath, MC.message);

    end
end



