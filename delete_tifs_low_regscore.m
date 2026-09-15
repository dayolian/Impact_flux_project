% delete_tifs_low_regscore.m
% Deletes *.tif files from pair subfolders where RegistrationScore < reg_threshold.
% Keeps all other files (TFW, auxiliary metadata, CSVs, MATs, JPEGs).
% Set dry_run = true to preview without deleting.

csv_path      = 'G:\crater_flux_output_folders\Impact_flux_project\pairsinfo_combo_master_alldata.csv';
reg_threshold = 0.25;
dry_run       = false;   % <- set to false only after reviewing dry run output

T = readtable(csv_path, 'Delimiter', ',', 'TextType', 'string');

low_reg = T.RegistrationScore < reg_threshold;
low_T   = T(low_reg, :);

fprintf('Total rows in CSV:       %d\n', height(T));
fprintf('Rows with score < %.2f:  %d\n', reg_threshold, height(low_T));

total_tifs_deleted = 0;
total_missing      = 0;

for i = 1:height(low_T)
    pairDir = low_T.wholepath(i);
    if ~isfolder(pairDir)
        total_missing = total_missing + 1;
        continue
    end

    tifs = [dir(fullfile(pairDir, '*.tif')); dir(fullfile(pairDir, '*.ovr'))];
    if isempty(tifs)
        continue
    end

    if dry_run
        fprintf('DRY RUN — would delete %d tif/ovr file(s) in: %s\n', length(tifs), pairDir);
    else
        for j = 1:length(tifs)
            delete(fullfile(pairDir, tifs(j).name));
        end
        fprintf('Deleted %d tif/ovr file(s) in: %s\n', length(tifs), pairDir);
    end
    total_tifs_deleted = total_tifs_deleted + length(tifs);
end

if dry_run
    fprintf('\nSummary: %d tif(s) would be deleted across %d subfolders (%d paths not found).\n', ...
        total_tifs_deleted, height(low_T) - total_missing, total_missing);
else
    fprintf('\nSummary: %d tif(s) deleted across %d subfolders (%d paths not found).\n', ...
        total_tifs_deleted, height(low_T) - total_missing, total_missing);
end
