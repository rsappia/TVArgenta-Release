# TVArgenta---Retro-TV

TVArgenta is a retro-style TV built with a Raspberry Pi that brings back the experience of channel surfing between commercials and offline content. It includes a local backend to manage videos, channels, and metadata — all inside a 3D-printed case.

# Part One: Basic Raspberry Pi Configuration

We prepare the SD card (in this case, I’m using a 64 GB one).
For that, we use Raspberry Pi Imager.
Make sure to select the following options:

<img width="683" height="320" alt="GetImage" src="https://github.com/user-attachments/assets/aa09a287-0f3b-446d-a764-79605f50f50e" />

In the hostname field, I make sure to set argentv.local (we’ll use it later, but you can choose any hostname you like).

<img width="516" height="98" alt="GetImage(1)" src="https://github.com/user-attachments/assets/0259456c-d82c-46b3-af1d-be7583b34bde" />

Make sure to configure the Wi-Fi credentials, language, and region.
Leave SSH enabled so you can access the Raspberry Pi remotely later on:

<img width="532" height="341" alt="GetImage(2)" src="https://github.com/user-attachments/assets/949f2aac-8162-4193-9738-f84d95144d0f" />

Click Install, and we’ll meet again in a few minutes 😉
[…]
Once the flashing process is done, insert the SD card into the Raspberry Pi.
If you see the following screens, you’re on the right track:

<img width="916" height="660" alt="GetImage(3)" src="https://github.com/user-attachments/assets/32d95c7d-202e-4d88-b238-08b752fa1662" />

<img width="893" height="584" alt="GetImage(4)" src="https://github.com/user-attachments/assets/6bbc4965-9e22-46e6-9d14-69f55224ef5f" />

Next, we’ll try to access the Raspberry Pi remotely.
Open your command console and type:

ssh argentv.local

You might see the following message:
<img width="688" height="245" alt="GetImage(5)" src="https://github.com/user-attachments/assets/33ae5eb5-0f7b-4cea-a7e9-fd71d36787e5" />

If that happens, try this:

`ssh-keygen -R argentv.local`

<img width="551" height="113" alt="GetImage(6)" src="https://github.com/user-attachments/assets/3e24967a-1ba1-44b9-8a79-5bd007d71a1b" />

Once done, try again with ssh argentv.local, and this time you should see something like this:

<img width="842" height="262" alt="GetImage(7)" src="https://github.com/user-attachments/assets/e2def0f8-fb5e-4c8f-9d6c-fb658fdf6e69" />

After typing yes, new certificates will be installed, and the SSH connection to the Raspberry Pi will be established.

During the setup, my username was “rs”.
Yours might differ — keep that in mind for the next steps.

Since this is the very first boot after formatting the SD card, let’s run the following commands:

`sudo apt update && sudo apt upgrade –y`

Now let’s clone the GitHub repository.
Before that, we need to configure our SSH keys.

### 1) If you already have SSH keys, skip this step

`ls -l ~/.ssh/id_ed25519 ~/.ssh/id_ed25519.pub 2>/dev/null || true`

### 2) Generate a new key (ED25519). Choose a helpful comment:

`ssh-keygen -t ed25519 -C "pi@argentv"`

Press Enter to accept the default path (`~/.ssh/id_ed25519`).
You can leave the passphrase empty (just press Enter) or add one for better security.

### 3) Show the public key (this one goes to GitHub)

`cat ~/.ssh/id_ed25519.pub`

### 4) (Optional) Load it into the SSH agent so you don’t have to enter your passphrase every time
```
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
```
Copy that public key and add it to your GitHub account:
GitHub → your avatar → Settings → SSH and GPG keys → New SSH key → paste the key.

### 5) Test the connection with GitHub (it should greet you with your username)

`ssh -T git@github.com`

If everything works, you’ll get a message like:
"Hi [user]! You’ve successfully authenticated, but GitHub does not provide shell access."

Now let’s prepare the directory where we’ll clone the repository.
Make sure /srv exists (it usually does) and give ownership to your user (again, my username is rs, but replace it with yours):
```
cd /srv
git clone git@github.com:rsappia/TVArgenta---Retro-TV.git tvargenta
cd /srv/tvargenta
```
<img width="729" height="202" alt="GetImage(8)" src="https://github.com/user-attachments/assets/28d59e5f-dd75-451f-a5ad-3bd34a4ce57b" />

## Install system and project dependencies

Run:
```
python3 -m venv venv
source venv/bin/activate
sudo apt update && sudo apt install -y python3 python3-pip && python3 -m pip install --upgrade pip && python3 -m pip install Flask
```
Let’s also prepare what’s needed to compile the encoder .c file:

`sudo apt install -y build-essential libgpiod-dev pkg-config`

Change directory to compile the encoder .c file:

`cd /srv/tvargenta/software/app/native`

Once there, run the compiler:

`gcc encoder_reader.c -o encoder_reader $(pkg-config --cflags --libs libgpiod)`

If everything goes well, you should now see the compiled .bin file next to the .c one:

<img width="488" height="38" alt="GetImage(9)" src="https://github.com/user-attachments/assets/15f96bbc-3f7a-4fe5-aab7-132335df9cc2" />

Now let’s set the proper permissions:
```
chmod +x encoder_reader
cd /srv/tvargenta/software
chmod +x scripts/*.sh
```
At this point, we can run a first test to make sure everything’s working.
Go to:

`cd /srv/tvargenta/software/app $`

and then run:

`python main.py`

If everything’s fine, you should see an intro video, followed by the playback of channels — which for now will be empty and in their default state, meaning you’ll see a “black screen.”

Try turning or pressing the encoder knob to bring up the menu.

Let’s add a few videos to make sure everything’s working properly.
You can use the videos already included in:

`/srv/tvargenta/software/app/assets/Splash/videos`

These come by default in the GitHub repo.

![TVArgenta first load](https://github.com/rsappia/TVArgenta-Release/blob/main/docs/TVArgenta_first_load.gif)

With this, you’re already good to go and play around.
In the next chapter, I’ll cover audio configuration, and in a third one, everything related to the hardware itself.

<p align="center"> 
    <em>If this project brought you a smile or inspired you to build something of your own,<br>
    buy me a coffee and let’s keep making Argentinian magic ☕🇦🇷</em> 
</p> 

<p align="center"> 
    <a href="https://paypal.me/RicardoSappia/5" target="_blank"> 
        <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" width="200"> 
    </a> 
</p> ---

