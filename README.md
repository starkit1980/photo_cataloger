# photo_cataloger

**License**: MIT | **Language**: Python 3.10+

## Description
A tool (simple python script) that searches for files and creates Photo catalog in html form.
The extensions of the files that are searched for are hardcoded in the script at the beginning in the following lists:
 - EXTS = [".jpg", ".jpeg"]
 - ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz"}

## Requirements:
 - windows, python, pillow

## Usages
Run in the cmd:
```bash
python create_photo_catalog.py -r <folder/disk>
```
or:
```bash
python create_photo_catalog.py -r <folder/disk> -p
```
Note: '-r' - to specify folder (default= C:/), '-p' - to skip scan and use existing DB

## Output

### Pictures:
 - Catalog/file_data_sorted.html - List in ascending order of file date
 - Catalog/exif_data_sorted.html - List of exif dates in ascending order
 - Catalog/camera_sorted.html - List by camera
 - Catalog/simple.html - A simple list
 - Catalog/size_sorted.html - List in descending order of size

### Archives:
 - Catalog/archives_by_path.html - Archives by path
 - Catalog/archives.html - Archives by date
 - Catalog/archives_by_size.html - Archives by size
 - Catalog/archives_by_ext.html - Archives by extension

The remaining files and folders in the 'Catalog' are auxiliary, but necessary.

## Known issues:
- In large sorted lists, empty rows may appear at the very end of the table labeled "Loading...."

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

> **Note**: Without a license, the code is under exclusive copyright by default. This means no one can copy, distribute, or modify your work without facing potential legal consequences. Adding a license (like MIT) explicitly grants these permissions, making it clear how others can use your code.
