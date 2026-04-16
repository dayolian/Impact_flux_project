% Fresh_Crater_Finder_and_Crops.m
%
% Merged script combining:
%   - Fresh_Crater_Finder_reup.m       (detection + candidates_t.mat)
%   - image_realign_and_minicrops.m    (registration score + jpeg crops)
%
% Changes from originals:
%   - Single alignment pass per pair (was two passes across two scripts)
%   - Writes targets.csv alongside candidates_t.mat (same data, CSV format)
%   - Writes hit_list.csv per pair folder (prefix + processed=0 per hit)
%   - Writes/updates pairsinfo_with_tformscore.csv in mainDir
%   - Crops and saves jpegs immediately after detection (no second script needed)
%   - Skip logic: checks for targets.csv existence (signals full pipeline ran)
%     Previously: script 1 checked candidates_t.mat, script 2 checked RegistrationScore>0
%
% Backwards compatibility:
%   - candidates_t.mat: identical variables (ctxID, bx, by, LOC_pass, ARE_pass,
%                        PAR_pass, ECC_pass, CVA_pass)
%   - targets.csv columns: LOC_pass_1, LOC_pass_2, ARE_pass, PAR_pass, CVA_pass, ECC_pass
%   - hit_list.csv columns: prefix, processed
%   - pairsinfo_with_tformscore.csv columns: wholepath, ctxID, centerlon, centerlat,
%                                             areakm2, hits, hitratio, RegistrationScore
%   - Jpeg naming: hit_{ARE}_{x}_{y}_before.jpg / hit_{ARE}_{x}_{y}_after.jpg
%
% NOTE on areakm2: computed from geotiff spatial extent as
%   (XWorldLimits range * YWorldLimits range) / 1e6
% This assumes meters as the projected unit (Mars equirectangular/sinusoidal).
% Verify against your existing pairsinfo values and adjust if needed.
%
% Mackenzie Day / Updated 2026

close all; clear all; clc; warning('off')

%% ── CONFIGURATION ────────────────────────────────────────────────────────────

mainDir    = 'G:\crater_flux_output_folders';
masterFile = fullfile(mainDir, 'pairsinfo_with_tformscore.csv');
logFile    = fullfile(mainDir, 'error_log_combined.txt');

% Detection tuning parameters (see calibration_tuning_FINAL.m)
dt = 0.35;   % Difference threshold
ma = 35;     % Minimum region area (px)

% Alignment downscale factor
scale = 15;

% Jpeg crop size (pixels, square)
crop_size = 100;
half_size = crop_size / 2;

% How often to save pairsinfo to disk (every N pairs, plus always at end)
save_interval = 50;

%% ── LOAD REFERENCE SURFACE ───────────────────────────────────────────────────

load(fullfile(mainDir, 'impact_reference.mat'))
% Expects: xgrid, ygrid, zgrid, elngrid

%% ── LOAD OR INITIALIZE MASTER PAIRSINFO TABLE ───────────────────────────────
% If the master CSV already exists, load it so we can update rows in place.
% If not, we create it from scratch as we go.

pairsinfo_cols = {'wholepath','ctxID','centerlon','centerlat', ...
                  'areakm2','hits','hitratio','RegistrationScore'};

if isfile(masterFile)
    masterTable = readtable(masterFile, 'Delimiter', ',');
    % Ensure all expected columns exist (forward compatibility)
    for c = 1:length(pairsinfo_cols)
        if ~ismember(pairsinfo_cols{c}, masterTable.Properties.VariableNames)
            masterTable.(pairsinfo_cols{c}) = zeros(height(masterTable), 1);
        end
    end
else
    % Will be built row by row and saved at end / every save_interval pairs
    masterTable = table('Size', [0, length(pairsinfo_cols)], ...
        'VariableTypes', {'string','string','double','double', ...
                          'double','double','double','double'}, ...
        'VariableNames', pairsinfo_cols);
end

%% ── LOGGING ──────────────────────────────────────────────────────────────────

logID = fopen(logFile, 'a');

%% ── OUTER LOOP: OUTPUT FOLDERS ───────────────────────────────────────────────

folders = dir(mainDir);
folders = folders([folders.isdir]);
folders = folders(~ismember({folders.name}, {'.', '..'}));
folders = folders(startsWith({folders.name}, 'output'));

for k = 1:length(folders)

    folderPath = fullfile(mainDir, folders(k).name);
    fprintf('\nProcessing folder %d of %d: %s\n', k, length(folders), folderPath);

    try
        clearvars -except ...
            k folderPath folders mainDir logID logFile ...
            masterFile masterTable pairsinfo_cols ...
            dt ma scale crop_size half_size save_interval ...
            xgrid ygrid zgrid elngrid

        % ── Load pair list ────────────────────────────────────────────────────
        clip_csv = fullfile(folderPath, 'clip_pairs.csv');
        if ~isfile(clip_csv)
            fprintf('  No clip_pairs.csv found, skipping folder.\n');
            continue
        end

        % clip_pairs.csv is a single-row CSV of alternating ctx IDs
        [~, pair_list, ~] = xlsread(clip_csv);

        pair_count   = floor(length(pair_list) / 2);
        pairs_done   = 0;
        folder_hits  = 0;

        cd(folderPath);
        tic

        %% ── INNER LOOP: IMAGE PAIRS ──────────────────────────────────────────

        for i = 1:2:length(pair_list)

            pl1       = pair_list{i};
            pl2       = pair_list{i+1};
            name_root = [pl1, '_', pl2];
            pairDir   = fullfile(folderPath, name_root);

            try
                cd(pairDir)

                %% ── SKIP CHECK ───────────────────────────────────────────────
                % targets.csv existing means the full pipeline already ran for
                % this pair (detection + crops + registration score all done).
                if isfile('targets.csv')
                    fprintf('  Skipping (targets.csv exists): %s\n', name_root);

                    % Still count hits for folder summary if needed
                    try
                        tgt = readtable('targets.csv');
                        folder_hits = folder_hits + height(tgt);
                    catch
                    end

                    cd(folderPath);
                    pairs_done = pairs_done + 1;
                    continue
                end

                ctx1  = [name_root, '_clippedB.tif'];   % Before image
                ctx2  = [name_root, '_clippedA.tif'];   % After image

                if ~isfile(ctx1) || ~isfile(ctx2)
                    fprintf('  Missing tif files for %s, skipping.\n', name_root);
                    cd(folderPath);
                    continue
                end

                fprintf('  Pair %d of %d: %s\n', (i+1)/2, pair_count, name_root);

                %% ── LOAD IMAGES ──────────────────────────────────────────────

                [Ab, Rb] = geotiffread(ctx1);
                [Aa, Ra] = geotiffread(ctx2);

                % Center coordinates (meters, Mars projected)
                bx = mean(Rb.XWorldLimits);
                by = mean(Rb.YWorldLimits);

                % Overlap area in km² from geotiff spatial extent
                % Assumes projected units are meters. Verify against existing
                % pairsinfo values if unsure.
                width_m  = abs(Rb.XWorldLimits(2) - Rb.XWorldLimits(1));
                height_m = abs(Rb.YWorldLimits(2) - Rb.YWorldLimits(1));
                areakm2  = (width_m * height_m) / 1e6;

                %% ── PREPROCESS ───────────────────────────────────────────────

                Ab = uint8(Ab);
                Aa = uint8(Aa);

                Ab(Ab == 0)   = NaN;
                Aa(Aa == 0)   = NaN;
                Ab(Ab == 255) = NaN;
                Aa(Aa == 255) = NaN;

                Ab = int16(Ab);
                Aa = int16(Aa);

                % Normalization and contrast stretching
                Arange    = prctile(Aa, 95, 'all') - prctile(Aa, 5, 'all');
                Brange    = prctile(Ab, 95, 'all') - prctile(Ab, 5, 'all');
                contRatio = double(Brange) / double(Arange);
                Ad        = Aa - prctile(Aa, 5, 'all');
                Ad        = Ad * contRatio + prctile(Ab, 5, 'all');
                Ad        = Ad + (mean(mean(mean(Ab))) - mean(mean(mean(Ad))));

                Ab = uint8(Ab);
                Aa = uint8(Aa);
                Ad = uint8(Ad);

                %% ── ALIGNMENT (single pass) ──────────────────────────────────

                [tformEst, score] = imregcorr( ...
                    imresize(Ad, 1/scale), ...
                    imresize(Ab, 1/scale), ...
                    'translation');

                tformEst.T(3, 1:2) = tformEst.T(3, 1:2) .* scale;
                Rf = imref2d(size(Ab));
                Ad = imwarp(Ad, tformEst, 'OutputView', Rf);

                %% ── BINARY DIFFERENCE MAP ────────────────────────────────────

                B = double(Ab) ./ double(max(max(Ab)));
                D = double(Ad) ./ double(max(max(Ad)));
                BDdiff = sqrt((B - D).^2);

                window_size    = 5;
                wind           = ones(window_size, window_size) ./ (window_size^2);
                BDdiff_smoothed = conv2(BDdiff.^2, wind, 'same');

                BDL0 = logical(BDdiff_smoothed > dt.^2);
                BDL  = bwareafilt(BDL0, [ma, 12000]);

                %% ── REGION PROPERTIES ────────────────────────────────────────

                stats = regionprops(BDL, ...
                    'centroid', 'area', 'perimeter', ...
                    'eccentricity', 'convexarea', 'eulernumber');

                if isempty(stats)
                    % No candidates — write empty outputs and move on
                    writePairOutputs(pairDir, name_root, bx, by, ...
                        [], [], [], [], [], score, ...
                        areakm2, masterTable, pairsinfo_cols, masterFile);
                    [masterTable] = updateMasterTable(masterTable, pairsinfo_cols, ...
                        pairDir, name_root, bx, by, areakm2, 0, score);
                    cd(folderPath);
                    pairs_done = pairs_done + 1;
                    continue
                end

                statsM1 = [cat(1, stats.Centroid), ...
                           cat(1, stats.Area), ...
                           cat(1, stats.Perimeter), ...
                           cat(1, stats.Eccentricity), ...
                           cat(1, stats.ConvexArea), ...
                           cat(1, stats.EulerNumber)];

                LOC = statsM1(:, 1:2);
                ARE = statsM1(:, 3);
                PAR = (4 .* pi .* ARE) ./ statsM1(:, 4).^2;
                ECC = statsM1(:, 5);
                CVA = statsM1(:, 3) ./ statsM1(:, 6);
                ELN = statsM1(:, 7);

                %% ── COMPARE WITH REFERENCE SURFACE ──────────────────────────

                CVA_ref = interp2(xgrid, ygrid, zgrid,    PAR, ECC);
                ELN_ref = interp2(xgrid, ygrid, elngrid,  PAR, ECC);

                above  = CVA > CVA_ref & CVA < 1;
                elnchk = ELN >= ELN_ref - 3;
                dblchk = above & elnchk;

                %% ── EDGE REMOVAL ─────────────────────────────────────────────

                LOC_dbl      = LOC(dblchk, :);
                box_size     = 5;
                edge_remover = ones(size(LOC_dbl, 1), 1);
                [h, w]       = size(Ab);

                for j = 1:size(LOC_dbl, 1)
                    row = round(LOC_dbl(j, 2));
                    col = round(LOC_dbl(j, 1));
                    image_edge = [(row-box_size) <= 0, (row+box_size) > h, ...
                                  (col-box_size) <= 0, (col+box_size) > w];
                    if any(image_edge)
                        edge_remover(j) = 0;
                        continue
                    end
                    Ab_val = mean(mean(Ab(row-box_size:row+box_size, col-box_size:col+box_size)));
                    Ad_val = mean(mean(Ad(row-box_size:row+box_size, col-box_size:col+box_size)));
                    if Ab_val == 0 || Ad_val == 0
                        edge_remover(j) = 0;
                    end
                end

                %% ── COLLECT PASSING HITS ─────────────────────────────────────

                ARE_dbl = ARE(dblchk);
                PAR_dbl = PAR(dblchk);
                ECC_dbl = ECC(dblchk);
                CVA_dbl = CVA(dblchk);

                edge_remover = logical(edge_remover);
                LOC_pass = LOC_dbl(edge_remover, :);
                ARE_pass = ARE_dbl(edge_remover);
                PAR_pass = PAR_dbl(edge_remover);
                ECC_pass = ECC_dbl(edge_remover);
                CVA_pass = CVA_dbl(edge_remover);

                n_hits = length(ARE_pass);
                fprintf('    Hits: %d  |  Reg score: %.4f\n', n_hits, score);

                %% ── SAVE candidates_t.mat (backwards compat) ─────────────────

                ctxID = name_root;
                save('candidates_t.mat', 'ctxID', 'bx', 'by', ...
                    'LOC_pass', 'ARE_pass', 'PAR_pass', 'ECC_pass', 'CVA_pass');

                %% ── SAVE targets.csv ─────────────────────────────────────────
                % Columns match existing format exactly:
                % LOC_pass_1, LOC_pass_2, ARE_pass, PAR_pass, CVA_pass, ECC_pass

                if n_hits > 0
                    targetsTable = table( ...
                        LOC_pass(:,1), LOC_pass(:,2), ARE_pass, PAR_pass, CVA_pass, ECC_pass, ...
                        'VariableNames', {'LOC_pass_1','LOC_pass_2','ARE_pass', ...
                                          'PAR_pass','CVA_pass','ECC_pass'});
                else
                    targetsTable = table( ...
                        zeros(0,1), zeros(0,1), zeros(0,1), zeros(0,1), zeros(0,1), zeros(0,1), ...
                        'VariableNames', {'LOC_pass_1','LOC_pass_2','ARE_pass', ...
                                          'PAR_pass','CVA_pass','ECC_pass'});
                end
                writetable(targetsTable, 'targets.csv');

                %% ── SAVE hit_list.csv ────────────────────────────────────────
                % Columns: prefix, processed
                % prefix encodes hit_{ARE}_{x}_{y} matching jpeg filenames.
                % processed = 0 (unreviewed; GUI sets to 1 when assessed)

                if n_hits > 0
                    prefixes   = cell(n_hits, 1);
                    processedV = zeros(n_hits, 1);
                    for j = 1:n_hits
                        x = round(LOC_pass(j, 1));
                        y = round(LOC_pass(j, 2));
                        prefixes{j} = sprintf('hit_%d_%d_%d', ARE_pass(j), x, y);
                    end
                    hitListTable = table(prefixes, processedV, ...
                        'VariableNames', {'prefix', 'processed'});
                else
                    hitListTable = table(cell(0,1), zeros(0,1), ...
                        'VariableNames', {'prefix', 'processed'});
                end
                writetable(hitListTable, 'hit_list.csv');

                %% ── CROP AND SAVE JPEGS ──────────────────────────────────────

                for j = 1:n_hits
                    x = round(LOC_pass(j, 1));
                    y = round(LOC_pass(j, 2));

                    x_min = x - half_size + 1;
                    x_max = x + half_size;
                    y_min = y - half_size + 1;
                    y_max = y + half_size;

                    % Clamp to image bounds
                    crop_before = Ab( ...
                        max(1, y_min):min(size(Ab,1), y_max), ...
                        max(1, x_min):min(size(Ab,2), x_max));
                    crop_after = Ad( ...
                        max(1, y_min):min(size(Ad,1), y_max), ...
                        max(1, x_min):min(size(Ad,2), x_max));

                    % Pad both images symmetrically if hit is near edge
                    % (Fixed: original script only padded one image per branch)
                    [crop_before, crop_after] = padCrops( ...
                        crop_before, crop_after, ...
                        x, y, size(Ab), size(Ad), half_size, crop_size);

                    before_path = sprintf('hit_%d_%d_%d_before.jpg', ARE_pass(j), x, y);
                    after_path  = sprintf('hit_%d_%d_%d_after.jpg',  ARE_pass(j), x, y);

                    imwrite(crop_before, before_path, 'Quality', 80);
                    imwrite(crop_after,  after_path,  'Quality', 80);
                end

                %% ── UPDATE MASTER PAIRSINFO TABLE ────────────────────────────

                hitratio = 0;
                if areakm2 > 0
                    hitratio = n_hits / areakm2;
                end

                masterTable = updateMasterTable(masterTable, pairsinfo_cols, ...
                    pairDir, name_root, bx, by, areakm2, n_hits, score);

                folder_hits  = folder_hits + n_hits;
                pairs_done   = pairs_done + 1;

                % Periodic save of master table
                if mod(pairs_done, save_interval) == 0
                    fprintf('  Saving pairsinfo table (%d pairs done)...\n', pairs_done);
                    writetable(masterTable, masterFile);
                end

                cd(folderPath);

            catch MC
                fprintf('  Error on pair %s: %s\n', name_root, MC.message);
                fprintf(logID, 'Error in pair: %s\nMessage: %s\n\n', ...
                    fullfile(folderPath, name_root), MC.message);
                cd(folderPath);
            end

        end % inner pair loop

        fprintf('Folder done: %d pairs, %d hits. Time: %.1f s\n', ...
            pairs_done, folder_hits, toc);

        % Save master table at end of each output folder
        writetable(masterTable, masterFile);

    catch ME
        fprintf('Error in folder %s: %s\n', folderPath, ME.message);
        fprintf(logID, 'Error in folder: %s\nMessage: %s\n\n', folderPath, ME.message);
    end

end % outer folder loop

%% ── FINAL SAVE AND CLEANUP ───────────────────────────────────────────────────

writetable(masterTable, masterFile);
fclose(logID);
cd(mainDir);

% Signal completion
doneFile = fullfile(mainDir, 'script_done.txt');
doneID   = fopen(doneFile, 'a');
fclose(doneID);

fprintf('\nAll folders complete.\n');


%% ════════════════════════════════════════════════════════════════════════════
%% LOCAL FUNCTIONS
%% ════════════════════════════════════════════════════════════════════════════

function masterTable = updateMasterTable(masterTable, colNames, ...
        pairDir, ctxID, bx, by, areakm2, n_hits, score)
    % Add or update a row in the master pairsinfo table.

    hitratio = 0;
    if areakm2 > 0
        hitratio = n_hits / areakm2;
    end

    % Check if this pair already has a row (e.g. from a previous partial run)
    if ismember('wholepath', masterTable.Properties.VariableNames) && ...
            height(masterTable) > 0
        existing = find(strcmp(masterTable.wholepath, pairDir), 1);
    else
        existing = [];
    end

    newRow = {string(pairDir), string(ctxID), bx, by, ...
              areakm2, double(n_hits), hitratio, score};

    if ~isempty(existing)
        for c = 1:length(colNames)
            masterTable.(colNames{c})(existing) = newRow{c};
        end
    else
        newRowTable = cell2table(newRow, 'VariableNames', colNames);
        masterTable = [masterTable; newRowTable];
    end
end


function [out_before, out_after] = padCrops(crop_before, crop_after, ...
        x, y, sz_before, sz_after, half_size, crop_size)
    % Pad both crops symmetrically to crop_size x crop_size.
    % Fixes the original script's asymmetric padding (only one image was
    % padded depending on which branch of the if/elseif was taken).

    function crop = padOneCrop(crop, x, y, sz)
        [ch, cw] = size(crop);
        if ch < crop_size || cw < crop_size
            pad_top    = max(0, half_size - (y - 1));
            pad_bottom = max(0, half_size - (sz(1) - y));
            pad_left   = max(0, half_size - (x - 1));
            pad_right  = max(0, half_size - (sz(2) - x));
            crop = padarray(crop, [pad_top,    pad_left],  0, 'pre');
            crop = padarray(crop, [pad_bottom, pad_right], 0, 'post');
        end
    end

    out_before = padOneCrop(crop_before, x, y, sz_before);
    out_after  = padOneCrop(crop_after,  x, y, sz_after);
end
