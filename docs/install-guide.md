# Kith Contacts: start here

Kith Contacts helps you find people by what you remember about them: their team, their
manager, a project, a tag. It runs on your own computer, and your contacts stay there.

Setting it up takes three steps and about 20 minutes, most of it waiting. You don't need to
type any commands.

1. Install Docker Desktop. It's a free program that runs Kith Contacts for you.
2. Unzip Kith Contacts.
3. Double-click **Start Kith Contacts**.

## What you need

- **A Windows computer:** Windows 10 version 22H2 or Windows 11 version 23H2 or newer, with
  at least 8 GB of memory.
- **Or a Mac:** running one of the three newest versions of macOS.
- **An internet connection** for the first start. After that, Kith Contacts works offline.
- **About 5 GB of free disk space.**

Docker Desktop is free for personal use and for businesses with fewer than 250 employees
and less than US$10 million in yearly revenue. Larger organisations need a paid Docker
subscription.

## Step 1: Install Docker Desktop (once)

### On a Mac

1. Find out which kind of Mac you have. Click the Apple menu at the top left and choose
    **About This Mac**.
    - If it says **Chip: Apple M1, M2, M3** (or newer), you have Apple silicon.
    - If it says **Processor: … Intel**, you have an Intel Mac.
2. Go to [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
    and click **Download for Mac**. Choose **Apple Silicon** or **Intel** to match your Mac.
3. Open the downloaded **Docker.dmg**. Drag the Docker whale into the **Applications**
    folder.
4. Open **Docker** from your Applications folder.
    - Click **Accept** on the subscription agreement.
    - If Docker asks you to sign in or create an account, skip it. Kith Contacts doesn't
        need a Docker account.
5. Have Docker start by itself when you log in to your computer:
    1. In Docker Desktop, click the gear icon (**Settings**).
    2. Under **General**, turn on **Start Docker Desktop when you sign in to your computer**.
    3. Click **Apply**.

### On Windows

1. Check your Windows version. Open **Start**, then **Settings**, then **System**, then
    **About**, and look at **Version**.
    - Windows 10 needs **22H2**.
    - Windows 11 needs **23H2** or newer.
    - If yours is older, run Windows Update first.
2. Go to [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
    and click **Download for Windows**. Most computers need the standard **AMD64** download.
    Some laptops have a Snapdragon (ARM) chip: they need the **ARM** download, which Docker
    marks as early access.
3. Open **Docker Desktop Installer.exe**.
    - Keep **Use WSL 2** ticked, then click **OK**.
    - When it finishes, click **Close and restart**. Some installs ask you to sign out
        instead.
4. After the restart, Docker Desktop opens by itself. If it doesn't, open it from the Start
    menu.
    - Click **Accept** on the subscription agreement.
    - If Docker asks you to sign in, skip it.
    - If Docker says WSL needs to be installed or updated, follow its button, then restart
        if it asks.
5. Have Docker start by itself when you sign in to Windows:
    1. In Docker Desktop, click the gear icon (**Settings**).
    2. Under **General**, turn on **Start Docker Desktop when you sign in to your computer**.
    3. Click **Apply & restart**.

Docker Desktop is ready when its window shows **Engine running** at the bottom left.

## Step 2: Unzip Kith Contacts

You were given a file named like `Kith-Contacts-1.0.0.zip`.

- **Mac:** double-click the zip in your Downloads folder. A folder named
  **KithContacts-1.0.0** appears next to it. You can move that folder anywhere, for
  example into Documents.
- **Windows:** right-click the zip and choose **Extract All…**, then click **Extract**. Use
  the folder this creates.

    > Don't open the files from inside the zip window. Windows only shows you a preview
    > there, and Start won't work.

## Step 3: Start it

### On a Mac

1. In the **KithContacts-1.0.0** folder you unzipped, double-click **Start Kith Contacts.command**.
2. The first time, macOS blocks it, saying it could not verify that the file is free of
    malware. That's because the file isn't registered with Apple, not because something is
    wrong. Allow it once:
    1. Click **Done**.
    2. Open the Apple menu, then **System Settings**, then **Privacy & Security**.
    3. Scroll down to **Security**. Next to the message about "Start Kith Contacts.command",
        click **Open Anyway**.
    4. Enter your Mac password, then click **Open Anyway** again.
3. A Terminal window opens and asks two questions. Answer them, then wait.

### On Windows

1. In the **KithContacts-1.0.0** folder you unzipped, double-click **Start Kith Contacts**. It may show as
    **Start Kith Contacts.bat**, of type *Windows Batch File*.
2. If a blue box says **Windows protected your PC**, click **More info**, then
    **Run anyway**. You only need to do this once.
3. A black window opens and asks two questions. Answer them, then wait.

### The two questions (first start only)

1. **Which contact books do you want?** Type **1** for Work, **2** for Personal or **3**
    for both, then press Enter (Return on a Mac).
    - **Work** starts with the contact types Employee, Customer and Vendor.
    - **Personal** starts with Family, Friend and Service provider.
    - You can change the types later in the app, under Settings.
2. **What should each contact book be called?** Type a name and press Enter, or just press
    Enter to keep "Work" or "Personal". The name shows at the top of every page.

**Now wait.** The first start takes 5 to 10 minutes while Docker builds Kith Contacts.
When it's ready, your browser opens it:

- Work: <http://localhost:5170>
- Personal: <http://localhost:5171>

**Bookmark the page.** You can close the window once it says *Kith Contacts is running*.

## Everyday use

- **Opening it:** use your bookmark. Kith Contacts starts by itself when you sign in to
  your computer, as long as Docker Desktop is set to start then (Step 1). Give it a minute
  after signing in.
- **If the page doesn't load:** double-click **Start Kith Contacts** again. It's always
  safe to do, and it's quick after the first time.
- **Stopping it:** double-click **Stop Kith Contacts**, or quit Docker Desktop. You
  normally don't need to.
- **Who can see it:** only someone using this computer. Other computers on your network
  can't open it.

## Your backups

Kith Contacts backs itself up every day while it runs. It also backs up before every
update, and before you restore an older backup.

- **Where the backups are:** in the **KithContacts** folder in your home folder.
  - **Mac:** open Finder, choose **Go**, then **Home**, then open **KithContacts**, then
        **Backups**.
  - **Windows:** `C:\Users\<your name>\KithContacts\Backups`
- **How long they're kept:** 14 days. The newest backup is never deleted.
- **Backing up or restoring yourself:** in the app, go to **Settings**, then **Backups**.
  You can back up now, download a backup, or restore one. To restore, you type the contact
  book's name to confirm.

For extra safety, copy the whole **KithContacts** folder to a USB drive or a cloud
folder now and then. It holds your contacts' details, so keep that copy somewhere safe. It's
also wise to turn on disk encryption on your computer: **FileVault** on a Mac, or
**BitLocker / Device encryption** on Windows.

## Moving to a new computer

1. **On the old computer:**
    1. In the app, go to **Settings**, then **Backups**, then **Back up now**.
    2. Double-click **Stop Kith Contacts**.
2. **Copy the whole KithContacts folder** from your home folder to the same place on the
    new computer. You can use a USB drive or a cloud folder. This works between a Mac and a
    Windows computer too.
3. **On the new computer:**
    1. Install Docker Desktop (Step 1).
    2. Unzip Kith Contacts (Step 2).
    3. Double-click **Start Kith Contacts** (Step 3).

    It won't ask the questions again, and your contacts come back automatically from the
    newest backup.

## Updating to a new version

1. Unzip the new version (Step 2). Your contacts aren't stored in the program folder, so you
    can delete the old one afterwards.
2. Double-click **Start Kith Contacts** in the new folder. This takes 5 to 10 minutes.
    Kith Contacts takes a backup before it changes anything.
3. To check which version you have, go to **Settings** and look at **This instance**,
    then **Version**.

## Changing names, colors or ports

Your answers are saved in **settings.env** in the KithContacts folder in your home folder. To change them:

1. Open **settings.env** with a plain text editor.
    - **Mac:** right-click, choose **Open With**, then **TextEdit**.
    - **Windows:** right-click, choose **Open with**, then **Notepad**.
2. Change the value after the `=` sign. Keep any quotes around it.
3. Save the file, then double-click **Start Kith Contacts**.

Things you can change:

- **Add the other contact book:** change `COMPOSE_PROFILES=work` to
  `COMPOSE_PROFILES=work,personal`.
- **Colors:** `WORK_COLOR` and `PERSONAL_COLOR`, as `#` followed by six hex digits.
- **Ports, if another program already uses 5170 or 5171:** `WORK_PORT` and
  `PERSONAL_PORT`. Use numbers from 1024 to 65535.

Pick names you're happy with early on. Backup file names start with the contact book's
name, and Settings only lists backups made under the current name. Older backups stay in
the folder.

## Removing Kith Contacts

1. Double-click **Stop Kith Contacts**.
2. In Docker Desktop, go to **Containers** and delete **kith-contacts**.
3. Then go to **Volumes** and delete the volumes whose names start with
    `kith-contacts_`. **This permanently deletes your contacts**, except for the backups
    in your KithContacts folder.
4. Delete the program folder. Delete the **KithContacts** folder in your home folder
    too, if you no longer need the backups.
5. If nothing else uses Docker Desktop, uninstall it:
    - **Mac:** drag Docker from Applications to the Bin.
    - **Windows:** go to **Settings**, then **Apps**.

## Something went wrong

| What you see | What to do |
| --- | --- |
| **Mac:** "Start Kith Contacts.command" Not Opened, or Apple could not verify… | Follow Step 3 on a Mac: **Privacy & Security**, then **Open Anyway**. |
| **Windows:** "Windows protected your PC" | Click **More info**, then **Run anyway**. |
| **Windows:** the window flashes and closes, or says it can't find `program\deploy\…` | You started it from inside the zip. Use **Extract All…** (Step 2) and start it from the extracted folder. |
| "Docker Desktop is not installed yet" | Do Step 1, then start again. |
| "Docker Desktop did not finish starting" | Open Docker Desktop and wait until it shows **Engine running**, then start again. If it never gets there, restart your computer. |
| **Windows:** Docker says virtualization is disabled or not detected | Virtualization has to be switched on in your computer's firmware (BIOS/UEFI). Open **Settings**, then **System**, then **Recovery**, then **Advanced startup**, then **Restart now**. Then choose **Troubleshoot**, **Advanced options**, **UEFI Firmware Settings**. Turn on **Intel Virtualization Technology (VT-x)** or **SVM Mode** (AMD), then save and exit. On a work computer, ask your IT department. |
| **Windows:** Docker says WSL needs updating | Click Docker's update button and restart if it asks. |
| "port is already allocated" or "address already in use" | Another program uses that port. Change `WORK_PORT` or `PERSONAL_PORT` in settings.env (see above), then start again. |
| "failed to resolve", "network" or "timeout" during the first start | Check the internet connection and start again. Some work networks block the downloads: use another network for the first start, or ask your IT department. |
| "Cannot write backups" | Kith Contacts won't run without working backups. Check that the **KithContacts** folder in your home folder belongs to you and isn't locked or read-only (Mac: select it, **File**, **Get Info**, **Sharing & Permissions**). Then start again. |
| The browser says "This site can't be reached" | Wait a minute after signing in, then reload. If it still fails, double-click **Start Kith Contacts**. |
| Settings says search by meaning is off | Its language model couldn't be downloaded during the first start. Everything else works. It will try again with the next update. |
| Anything else | Copy the text in the window and send it to whoever gave you Kith Contacts. More detail is in Docker Desktop: go to **Containers**, then **kith-contacts**, then **work** (or **personal**), then **Logs**. |

## How it works

- **What runs:** Docker Desktop runs Kith Contacts as a small group of programs named
  **kith-contacts**: a database, plus one app for each contact book.
- **Passwords:** they're created on the first start and kept inside Docker. You never need
  to know them.
- **Internet use:** Kith Contacts sends nothing to the internet. It only downloads during
  the first start and after an update, while it's being built.
