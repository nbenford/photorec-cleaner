# PhotoRec Cleaner

A command-line utility to intelligently organize files recovered by [PhotoRec](https://www.cgsecurity.org/wiki/PhotoRec). It actively monitors the PhotoRec output directory, deletes unwanted file types from completed `recup_dir.X` folders in real-time.

![While running](https://i.imgur.com/NaiEfDp.png)
![After running](https://i.imgur.com/4c2jbBD.png)

## Why Does This Exist?

Sometimes you only need to recover a handful of file types, but your drive can quickly get filled by thousands of unwanted image and text files. The catch is that the more file types PhotoRec parses, the better the output. Only searching for one or two types can result in erroneously huge files.

Photorec Cleaner allows PhotoRec to parse all file types, but actively deletes unwated types in real time to keep the output tidy. It also can reorganize the kept files into a type-based folder structure, as well as create a log of all deleted and kept files.

> [!NOTE]
>This early version of the script shouldn't be used for critical forensic applications. Use at your own risk.

Please [email me](mailto:noel.benford@gmail.com) with any issues, questions, comments, or suggestions. Thanks!

Sincerely,
Noel

## Requirements

- Python 3.6+

No external libraries are required. The script uses only standard Python modules.

## Installation

There are two ways to install and run this application, depending on your needs.

### Method 1: Standard Install

This is the standard method for installing the application for regular use. It builds a package and installs it, making the `photorec-cleaner` command available in your terminal.

1. **Install the build tool:**

   ```bash
   pip install build
   ```

2. **Build the package:** From the project's root directory, run:

   ```bash
   python -m build
   ```

3. **Install the built package**: This command uses a wildcard (`*`) to automatically find the `.whl` file in the `dist` directory, so you don't have to type the version number.

   ```bash
   pip install dist/photorec_cleaner-*.whl
   ```

### Method 2: Running as a Script (No Installation)

If you prefer not to install the package, you can run it directly as a Python script.

1. From the project's root directory, execute the main module:

   ```bash
   python src/photorec_cleaner/photorec_cleaner.py [OPTIONS]
   ```

## Command-Line Arguments

> [!IMPORTANT]
> **You must provide an input directory (`-i`) and at least one filtering rule (`-k` or `-x`).**

| Argument              | Short | Description                                                                                                          |
| --------------------- | ----- | -------------------------------------------------------------------------------------------------------------------- |
| `--input <path>`      | `-i`  | **(Required)** Path to the PhotoRec output directory.                                                                |
| `--keep <ext ...>`    | `-k`  | Defines an **allow list**. Only files with these extensions will be kept; all others are deleted.                    |
| `--exclude <ext ...>` | `-x`  | Defines a **deny list**. Files with these extensions will be deleted. This rule overrides `--keep` if both are used. |
| `--reorganize`        | `-r`  | After cleaning, move kept files into folders named by file type and remove the old `recup_dir.X` folders.            |
| `--log`               | `-l`  | Log all file actions (kept/deleted) to a timestamped CSV file in the output directory.                               |
| `--interval <sec>`    | `-t`  | Seconds between scanning for new folders. Defaults to `5`.                                                           |
| `--batch-size <num>`  | `-b`  | Max number of files per subfolder when reorganizing. Defaults to `500`.                                              |

## Usage

The command to run the application depends on your installation method.

- **If installed via Method 1**, use the `photorec-cleaner` command.
- **If running as a script (Method 2)**, use `python src/photorec_cleaner/photorec_cleaner.py`.

For simplicity, the examples below use the `photorec-cleaner` command.

```bash
photorec-cleaner -i /path/to/photorec_output [OPTIONS]
```

### Examples

**Example 1: Keep only common image and document files.**

```bash
photorec-cleaner -i /path/to/output -k jpg jpeg png gif pdf doc docx
```

**Example 2: Keep everything _except_ temporary and system files, and reorganize the results.**

```bash
photorec-cleaner -i /path/to/output -x tmp chk dat -r
```

**Example 4: Keep gz files except xml.gz and html.gz, polls every 1 second, logs actions, and used 1000 files per subfolder in the reorg.**

```bash
photorec-cleaner -i /path/to/output -k gz -x xml.gz html.gz -t 1 -l -r -b 1000
```

## How It Works

1. Start Photorec Cleaner before starting recovery with PhotoRec. The status spinner will be **gray** until PhotoRec creates the first `recup_dir.1` folder.
1. Once PhotoRec Cleaner detects folders, the spinner turns **blue**.
1. As soon as PhotoRec creates a second folder (e.g., `recup_dir.2`), the script assumes the first one is complete. It begins cleaning `recup_dir.1` based on your rules. The spinner turns **green**.
1. This process continues, with the script always cleaning all but the highest-numbered `recup_dir.X` folder.
1. When PhotoRec finishes, press `y` and then `Enter`. The script will perform a final pass to clean all remaining folders.
1. If `-r` (`--reorganize`) is used, it will then move all kept files into their new folders/subfolders, and the `recup_dir.X` folders will be removed.

## Running Tests

Unit tests are located in the `tests/` directory. You can run them from the project's root directory using Python's built-in test discovery:

```bash
python -m unittest discover
```
