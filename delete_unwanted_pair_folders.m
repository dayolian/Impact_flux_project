% delete_unwanted_pair_folders.m
% Deletes entire pair subfolders that fall outside the useful range:
%   - RegistrationScore < reg_threshold, OR
%   - hits >= hits_threshold
% Keeps all other files in the output_ folder (shapefiles, etc.)
% Pairs not yet in the CSV are untouched.
% Set dry_run = true to preview without deleting.

csv_path       = 'G:\crater_flux_output_folders\Impact_flux_project\pairsinfo_with_tformscore.csv';
hits_threshold = 31;
reg_threshold  = 0.25;
dry_run        = false;   % <- set to false only after reviewing dry run output

T = readtable(csv_path, 'Delimiter', ',', 'TextType', 'string');

to_delete = T.RegistrationScore < reg_threshold | T.hits >= hits_threshold;
del_T     = T(to_delete, :);
keep_T    = T(~to_delete, :);

fprintf('Total rows in CSV:       %d\n', height(T));
fprintf('Subfolders to DELETE:    %d\n', height(del_T));
fprintf('Subfolders to KEEP:      %d\n', height(keep_T));

total_deleted = 0;
total_missing = 0;

for i = 1:height(del_T)
    pairDir = char(del_T.wholepath(i));
    if ~isfolder(pairDir)
        total_missing = total_missing + 1;
        continue
    end

    if dry_run
        fprintf('DRY RUN — would delete folder: %s\n', pairDir);
    else
        rmdir(pairDir, 's');
        fprintf('Deleted: %s\n', pairDir);
    end
    total_deleted = total_deleted + 1;
end

if dry_run
    fprintf('\nSummary: %d folders would be deleted (%d paths not found).\n', ...
        total_deleted, total_missing);
else
    fprintf('\nSummary: %d folders deleted (%d paths not found).\n', ...
        total_deleted, total_missing);
end
