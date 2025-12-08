from huggingface_hub import hf_hub_download, login, list_repo_files
import os

repo_id = "change this to repo id"

# Local download directory
download_dir = "you can change this to your own directory"
os.makedirs(download_dir, exist_ok=True)

# List and download all files from the dataset
all_files = list_repo_files(repo_id=repo_id, repo_type="dataset")

for file in all_files:
    print(f"Downloading: {file}")
    file_path = hf_hub_download(
        repo_id=repo_id,
        filename=file,
        repo_type="dataset",
        local_dir=download_dir,
        local_dir_use_symlinks=False
    )
    print(f"Saved to: {file_path}")