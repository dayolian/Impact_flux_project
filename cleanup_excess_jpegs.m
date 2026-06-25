% cleanup_excess_jpegs.m
% Deletes all JPEGs from pair subfolders that contain more than jpeg_threshold JPEGs.
% Set dry_run = true to preview without deleting.
% To test on a single folder, change the folders filter line below.

mainDir        = 'G:\crater_flux_output_folders\Impact_flux_project';
jpeg_threshold = 30;
dry_run        = false;   % ← set to false only after reviewing dry run output

% To test on a single folder, replace the startsWith line with e.g.:
% folders = folders(strcmp({folders.name}, 'output_-115_-110_-15_-10'));
folders = dir(mainDir);
folders = folders([folders.isdir]);
folders = folders(~ismember({folders.name}, {'.', '..'}));
folders = folders(startsWith({folders.name}, 'output_new_80_90_0_75'));

total_folders_affected = 0;
total_jpegs_deleted    = 0;

for k = 1:length(folders)
    folderPath = fullfile(mainDir, folders(k).name);
    subDirs = dir(folderPath);
    subDirs = subDirs([subDirs.isdir]);
    subDirs = subDirs(~ismember({subDirs.name}, {'.', '..'}));

    for i = 1:length(subDirs)
        pairDir = fullfile(folderPath, subDirs(i).name);
        jpegs   = dir(fullfile(pairDir, '*.jpg'));

        if length(jpegs) > jpeg_threshold
            total_folders_affected = total_folders_affected + 1;
            total_jpegs_deleted    = total_jpegs_deleted + length(jpegs);

            if dry_run
                fprintf('DRY RUN — would delete %d jpegs in: %s\n', ...
                    length(jpegs), pairDir);
            else
                for j = 1:length(jpegs)
                    delete(fullfile(pairDir, jpegs(j).name));
                end
                fprintf('Deleted %d jpegs in: %s\n', length(jpegs), pairDir);
            end
        end
    end
end

if dry_run
    fprintf('\nSummary: %d subfolders affected, %d jpegs would be deleted.\n', ...
        total_folders_affected, total_jpegs_deleted);
else
    fprintf('\nSummary: %d subfolders affected, %d jpegs deleted.\n', ...
        total_folders_affected, total_jpegs_deleted);
end
