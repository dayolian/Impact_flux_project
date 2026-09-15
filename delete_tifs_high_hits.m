% delete_tifs_high_hits.m
% Deletes *.tif and *.ovr files from pair subfolders where:
%   - hits >= hits_threshold (too noisy to save crops), OR
%   - RegistrationScore < reg_threshold (too poorly aligned to be useful)
% Set dry_run = true to preview without deleting.

csv_path       = 'G:\crater_flux_output_folders\Impact_flux_project\pairsinfo_combo_master_alldata.csv';
hits_threshold = 31;
reg_threshold  = 0.25;
dry_run        = false;   % <- set to false only after reviewing dry run output

T = readtable(csv_path, 'Delimiter', ',', 'TextType', 'string');

to_delete = T.hits >= hits_threshold | T.RegistrationScore < reg_threshold;
del_T     = T(to_delete, :);

fprintf('Total rows in CSV:                     %d\n', height(T));
fprintf('Rows with hits >= %d or score < %.2f:  %d\n', hits_threshold, reg_threshold, height(del_T));

total_files_deleted = 0;
total_missing       = 0;

for i = 1:height(del_T)
    pairDir = del_T.wholepath(i);
    if ~isfolder(pairDir)
        total_missing = total_missing + 1;
        continue
    end

    files = [dir(fullfile(pairDir, '*.tif')); dir(fullfile(pairDir, '*.ovr'))];
    if isempty(files)
        continue
    end

    if dry_run
        fprintf('DRY RUN — would delete %d file(s) in: %s\n', length(files), pairDir);
    else
        for j = 1:length(files)
            delete(fullfile(pairDir, files(j).name));
        end
        fprintf('Deleted %d file(s) in: %s\n', length(files), pairDir);
    end
    total_files_deleted = total_files_deleted + length(files);
end

if dry_run
    fprintf('\nSummary: %d tif/ovr file(s) would be deleted across %d subfolders (%d paths not found).\n', ...
        total_files_deleted, height(del_T) - total_missing, total_missing);
else
    fprintf('\nSummary: %d tif/ovr file(s) deleted across %d subfolders (%d paths not found).\n', ...
        total_files_deleted, height(del_T) - total_missing, total_missing);
end
