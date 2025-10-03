# Canvas Grabber

Canvas Grabber is a Python command-line tool for downloading course content from Instructure Canvas.  
It allows you to select a course, choose modules, and download all available files (including those inside pages and assignments) into organized folders on your computer.
![Demo GIF](Canvas-Grabber/usage.gif)

---

## Features
- Command-line interactive interface
- Prompts for your Canvas domain (example: `canvas.odu.edu`) and API token (entered once per session)
- Lists your enrolled courses so you can select one
- Lists modules and allows multiple selections (example: `8,9,6` or `5-7`)
- Downloads:
  - Direct file items
  - Files linked in pages
  - Assignment attachments
- Saves to: `~/Documents/<Course Name>/<Module Title>/`
- After downloading, returns to the course list without asking for credentials again

---

## Requirements
- Python 3.9 or later
- Install dependencies:
  ```bash
  pip install requests tqdm
  ```
- Optional (for colored output and ASCII banner):
  ```bash
  pip install colorama pyfiglet
  ```

  ---

## Getting a Canvas API Token
1. Log in to your Canvas account in a browser.
2. Click **Account** → **Settings**.
3. Scroll down to **Approved Integrations** → click **+ New Access Token**.
4. Copy the generated token and keep it private.

---

## Usage

1. Save the script as `canvas_grabber.py`.
2. Run in a terminal:
   ```bash
   python canvas_grabber.py
   ```
3. Follow the prompts:
   - Enter your Canvas domain (example: `canvas.odu.edu`)
   - Enter your API token
   - Select a course
   - Select modules (example: `2,3` or `1-3`)

Files will be saved to:
```
Documents/<Course Name>/<Module Title>/
```

---

## Notes
- External links (such as OneDrive or publisher tools) are not downloadable through the Canvas API.
- The script will skip locked or restricted items.
- Treat your API token like a password.
