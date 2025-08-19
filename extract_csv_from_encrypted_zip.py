#!/usr/bin/env python3
"""
Extract CSV file(s) from an encrypted ZIP using a password loaded from a .env file.

Usage:
  python extract_csv_from_encrypted_zip.py /path/to/file.zip
  python extract_csv_from_encrypted_zip.py /path/to/file.zip --env-file /path/to/.env --env-var ZIP_PASSWORD
"""

import argparse
import os
import sys
from pathlib import Path
import shutil

from dotenv import load_dotenv
import pyzipper


def extract_csvs(zip_path: Path, password: str, output_dir: Path) -> list[Path]:
    """
    Extract only CSV files from an encrypted ZIP into output_dir.
    Files are flattened (nested paths inside the ZIP are ignored for the output filename).
    Returns list of extracted file paths.
    """
    extracted: list[Path] = []

    if not zip_path.exists() or not zip_path.is_file():
        raise FileNotFoundError(f"ZIP not found: {zip_path}")

    if not password:
        raise ValueError("Password is empty or not provided.")

    pwd_bytes = password.encode("utf-8")

    # pyzipper supports AES and legacy ZipCrypto
    with pyzipper.AESZipFile(zip_path) as zf:
        zf.pwd = pwd_bytes
        members = [n for n in zf.namelist() if n.lower().endswith(".csv") and not n.endswith("/")]

        if not members:
            return extracted  # no CSVs inside

        for name in members:
            out_path = output_dir / Path(name).name  # flatten any internal folders
            # Stream to disk to avoid loading large files fully into memory
            with zf.open(name, "r") as src, open(out_path, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)  # 1MB chunks
            extracted.append(out_path)

    return extracted


def main():
    parser = argparse.ArgumentParser(description="Extract CSV(s) from an encrypted ZIP using a .env password.")
    parser.add_argument("zip_path", help="Path to the encrypted .zip")
    parser.add_argument("--env-file", default=None, help="Path to .env (defaults to current working dir)")
    parser.add_argument("--env-var", default="ZIP_PASSWORD", help="Env var name holding the ZIP password (default: ZIP_PASSWORD)")
    args = parser.parse_args()

    # Load .env
    load_dotenv(args.env_file)  # None ⇒ default locations

    password = os.getenv(args.env_var)
    if not password:
        print(f"Environment variable {args.env_var} not set. Add it to your .env or environment.", file=sys.stderr)
        sys.exit(2)

    zip_path = Path(args.zip_path).expanduser().resolve()
    output_dir = zip_path.parent

    try:
        extracted = extract_csvs(zip_path, password, output_dir)
    except pyzipper.BadZipFile:
        print("The ZIP appears to be corrupted or unreadable.", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        # Common from pyzipper when the password is wrong.
        if "password" in str(e).lower():
            print("Decryption failed. Check that the password is correct.", file=sys.stderr)
        else:
            print(f"Decryption/runtime error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not extracted:
        print("No CSV files found in the archive.")
        sys.exit(0)

    print("Extracted CSV files:")
    for p in extracted:
        print(f"  {p}")


if __name__ == "__main__":
    main()
