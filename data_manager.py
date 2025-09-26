#!/usr/bin/env python3
"""
Data management utilities for PR metrics
"""
import pandas as pd
from pathlib import Path
import re
from datetime import datetime

OUTPUT_DIR = "output"

def cleanup_old_files(keep_latest=3):
    """Remove old parquet files, keeping only the latest N files"""
    files = sorted(Path(OUTPUT_DIR).glob("*.parquet"))
    if len(files) <= keep_latest:
        print(f"📁 Only {len(files)} files, no cleanup needed")
        return

    files_to_remove = files[:-keep_latest]
    print(f"🗑️  Removing {len(files_to_remove)} old files...")

    for file in files_to_remove:
        print(f"   Removing {file.name}")
        file.unlink()

    print(f"✅ Kept latest {keep_latest} files")

def merge_and_dedupe_all():
    """Merge all parquet files and deduplicate"""
    files = sorted(Path(OUTPUT_DIR).glob("*.parquet"))
    if not files:
        print("No parquet files found")
        return None

    print(f"🔄 Merging {len(files)} parquet files...")

    # Load all data
    all_dfs = []
    for file in files:
        df = pd.read_parquet(file)
        df['source_file'] = file.name
        all_dfs.append(df)

    # Combine all data
    combined_df = pd.concat(all_dfs, ignore_index=True)
    print(f"📊 Combined: {len(combined_df)} total records")

    # Deduplicate by repo + pr_number (keeping latest data)
    original_count = len(combined_df)
    deduped_df = combined_df.drop_duplicates(
        subset=['repo', 'pr_number'],
        keep='last'  # Keep the most recent version
    ).drop(columns=['source_file'])

    duplicates_removed = original_count - len(deduped_df)
    print(f"🔄 Removed {duplicates_removed} duplicates")
    print(f"✅ Final dataset: {len(deduped_df)} unique PRs")

    return deduped_df

def create_consolidated_file():
    """Create a single consolidated, deduplicated file"""
    df = merge_and_dedupe_all()
    if df is None:
        return

    # Save consolidated file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    consolidated_file = f"{OUTPUT_DIR}/pr_data_consolidated_{timestamp}.parquet"
    df.to_parquet(consolidated_file, index=False)

    print(f"💾 Saved consolidated file: {consolidated_file}")
    return consolidated_file

def incremental_merge_strategy(new_df, existing_file=None):
    """
    Smart merge for incremental updates
    - Load existing data
    - Merge with new data
    - Deduplicate
    - Save with timestamp
    """
    if existing_file is None:
        # Find latest file
        files = sorted(Path(OUTPUT_DIR).glob("*.parquet"))
        if not files:
            print("📁 No existing data, creating first file")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"{OUTPUT_DIR}/pr_data_incremental_{timestamp}.parquet"
            new_df.to_parquet(output_file, index=False)
            return output_file
        existing_file = files[-1]

    print(f"🔄 Merging with existing file: {existing_file.name}")

    # Load existing data
    existing_df = pd.read_parquet(existing_file)
    print(f"   Existing: {len(existing_df)} records")
    print(f"   New: {len(new_df)} records")

    # Combine and deduplicate
    combined_df = pd.concat([existing_df, new_df], ignore_index=True)
    original_count = len(combined_df)

    # Deduplicate by repo + pr_number, keeping newest data
    deduped_df = combined_df.drop_duplicates(
        subset=['repo', 'pr_number'],
        keep='last'
    )

    duplicates_removed = original_count - len(deduped_df)
    new_records = len(deduped_df) - len(existing_df) + duplicates_removed

    print(f"   Duplicates removed: {duplicates_removed}")
    print(f"   Net new records: {new_records}")
    print(f"   Final size: {len(deduped_df)} records")

    # Save incremental file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"{OUTPUT_DIR}/pr_data_incremental_{timestamp}.parquet"
    deduped_df.to_parquet(output_file, index=False)

    print(f"💾 Saved incremental file: {output_file}")
    return output_file

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Data management for PR metrics')
    parser.add_argument('--cleanup', action='store_true', help='Remove old parquet files')
    parser.add_argument('--consolidate', action='store_true', help='Create consolidated deduplicated file')
    parser.add_argument('--keep', type=int, default=3, help='Number of files to keep during cleanup')

    args = parser.parse_args()

    if args.cleanup:
        cleanup_old_files(keep_latest=args.keep)

    if args.consolidate:
        create_consolidated_file()