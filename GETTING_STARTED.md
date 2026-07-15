# Getting Started (plain-English setup)

This guide gets the app running on your own computer. **You do the setup once**
(about 15–20 minutes). After that, starting the app each day takes two short
commands.

Follow the steps for **your** computer — Windows or Mac. When you see a command
in a grey box, type or paste it exactly, then press **Enter**.

**What you'll need from me first:** the app files, your profile file (ends in
`.py`), and your API keys. Have those handy before you start.

---

## 1. Install Python

Python is the language the app runs on.

- Go to **https://www.python.org/downloads/** and click the big download button.
- **Windows — important:** on the first installer screen, check the box that says
  **"Add python.exe to PATH"** before clicking **Install Now**. (If you miss this,
  the app won't start later.)
- **Mac:** just run the installer normally.

---

## 2. Put the app in a folder

- Make a folder somewhere easy, e.g. `Documents\Prospecting` (Windows) or
  `Documents/Prospecting` (Mac).
- Put all the app files I sent you **inside** that folder. If they came as a ZIP,
  right-click it → **Extract All** (Windows) or double-click it (Mac). Make sure
  the files sit directly in the folder — if everything landed inside an extra
  nested folder, move it up one level.

---

## 3. Open the command line **in that folder**

The "command line" is a window where you type the commands below.

- **Windows:** open the folder in File Explorer. Click the address bar at the top,
  type `powershell`, and press **Enter**. A blue window opens.
- **Mac:** open the **Terminal** app (press ⌘+Space, type "Terminal", Enter). Type
  `cd ` (the letters c, d, and a space), then **drag your folder onto the Terminal
  window** and press **Enter**.

You should now be "in" your app folder.

---

## 4. Create your private workspace ("virtual environment")

This is a private sandbox so the app's parts don't interfere with the rest of your
computer. You only create it once.

**Create it:**

- Windows: `python -m venv venv`
- Mac: `python3 -m venv venv`

**Turn it on (do this every time you use the app):**

- Windows: `.\venv\Scripts\Activate.ps1`
- Mac: `source venv/bin/activate`

You'll know it worked because the line now starts with **`(venv)`**.

> **Windows hiccup:** if turning it on gives a red error about scripts being
> "disabled on this system," run this once, press **Y**, then try the turn-on
> command again:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

---

## 5. Install the app's parts

With `(venv)` showing, run:

```
pip install -r requirements.txt
```

Let it finish — it prints a lot of text; that's normal.

---

## 6. Add your API keys

The app needs keys to talk to Google, OpenAI, and Brave.

- Make your own settings file from the example:
  - Windows: `copy .env.example .env`
  - Mac: `cp .env.example .env`
- Open the new `.env` file in a plain text editor (Notepad on Windows, TextEdit on
  Mac) and paste your keys in after the `=` signs. Save and close.

(The `README.md` has a table explaining each key and where it comes from — or just
use the keys I gave you.)

---

## 7. Drop in your profile file

Put the profile file I sent you (for example `photographer.py`) into the
**`searcher_profiles`** folder inside your app folder. That one file tells the app
who to look for on your behalf.

---

## 8. Set up the app's database (one time)

```
flask db upgrade
```

This creates the small local database the app uses to remember your results.

---

## 9. Start the app

```
python app.py
```

Wait until you see a line mentioning `http://127.0.0.1:5000`. Open your web browser
and go to that address: **http://127.0.0.1:5000**

The app is now running.

---

## 10. Stop the app

Click back on the command-line window and press **Ctrl+C** (hold the **Ctrl** key
and press **C**). On a Mac it's also **Control+C** — the Control key, not Command.
The app stops and you get your prompt back. It's safe to close the window.

---

## Every day after that

You do **not** repeat the setup. To use the app again:

1. Open the command line in your app folder (Step 3).
2. Turn on the workspace (Step 4 "turn it on" command).
3. `python app.py`, then open **http://127.0.0.1:5000** in your browser.
4. Press **Ctrl+C** in the command window to stop when you're done.

---

## If something goes wrong

- **"python is not recognized" (Windows):** Python wasn't added to PATH. Reinstall
  it (Step 1) and be sure to check the **"Add python.exe to PATH"** box.
- **"command not found: python3" (Mac):** Python didn't install — redo Step 1.
- **Red "scripts disabled" error on Windows:** use the `Set-ExecutionPolicy` fix in
  the box under Step 4.
- **The browser page won't load:** make sure the command window still shows the app
  running (you haven't pressed Ctrl+C), and use the exact address
  `http://127.0.0.1:5000`.
- **Still stuck?** Send me the exact text in the command window and I'll sort it out.
