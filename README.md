# myOfflineAi-VoiceAssistant
> 
> Prototype - For testing, education and inspiration

<br>

YouTube Video Demo (Version 1.0)<br>
https://www.youtube.com/watch?v=rFboArOTe20<br>
The demo is in real time.<br>
Hardware: M4 Macbook Air, 16GB RAM, 512GB Storage

<br>

A truly offline Ai voice assistant that uses Flask for the backend, Whisper for Speech-to-Text (STT), Kokoro for Text-to-Speech (TTS), and Ollama for the Large Language Model (LLM).

This is a privacy-first desktop Ai voice assistant designed to provide transparent, auditable and fully offline AI access for self-employed professionals in regulated industries, researchers, teachers and students who need data privacy. The app has a full-featured, clean, intuitive interface with built-in support for text and voice input. It also supports image and pdf input. 

- Designed to be Offline-first, Privacy-first and fully Transparent
- Double-click a file to run. No need to use the command line after the initial setup.
- Runs on the desktop
- Single-file architecture - code is easy to audit because HTML, CSS, JS and Python are all in one file
- Easy to modify and audit using Ai. Simply give the Ai the app.py file and tell it what changes you want made or ask it to audit the code for privacy.
- Full featured - customize the system message, temperature, voice type and other settings.
- Supports text and voice input, and text and voice output
- Supports images and pdf files (drag and drop)
- For maximum privacy switch off your internet access and set Ollama to airplane mode

### Key innovations

The innovations are not in the development of new technologies, but in the creative use of existing ones.

- Single-file architecture (Easy to use Ai to audit the code and to customize the app)
- Double-click to run (More accessible to non-programmers)
- Sentence-by-sentence TTS via WebSockets (Speeds up audio response)

<br>

<img src="images/image1.png" alt="App screenshot" height="500">
<p>myOfflineAi App - Clean and modern interface</p>

<br>

<img src="images/image2.png" alt="App screenshot" height="500">
<p>myOfflineAi App - Voice mode enabled</p>

<br>

## Version 2: Faster Audio Response - Used WebSockets to Implement Sentence-by-Sentence TTS

<br>

In Version 1, the code waits for the model’s entire response to be generated before creating and playing the full audio. This causes a “thinking” delay, especially when the model’s response is long.

To solve this, Version 2 modifies the backend to stream the model’s response token-by-token to the front end using WebSockets. As text arrives, it is displayed immediately. This process allows sentence boundaries (like full stops or question marks) to be detected. Once a full sentence is received, that sentence is sent to the Kokoro TTS engine, converted to audio, and played right away. The result is that the voice starts speaking much sooner, making the conversation feel more fluid and natural.

In a Flask application running locally, your browser is the client and Flask is the server. The browser (client) sends requests — for example, when you open a page or click a button — and the Flask app (server) receives those requests, processes them, and sends back a response.

WebSockets provide a way for the browser and the server to keep an open line of communication. With regular web communication (HTTP), it’s like making a phone call every time you want to say something — you call, talk, hang up, and then call again. With WebSockets, it’s like keeping the call open the whole time, so both sides can talk and listen whenever they want without hanging up. This makes real-time features like live chat or streaming much faster and smoother.

To make this work, this app uses Flask-SocketIO, a library that adds WebSocket support to Flask applications.


<br>

## How to Install and Run

<br>

In this section you will do the following:
- Install the Ollama desktop app
- Download a small 250MB text-only Ollama model
- Install the UV Python package manager
- Install ffmeg
- Start the myOfflineAi app by double clicking a file

Notes:<br>
- I tested the installation process on MacOS. Although I've included instructions for Windows, I haven't tested on Windows.
- After setup, you only need to double-click a file to launch the app.

System Requirements:
- Computer: Apple Silicon Mac (M-series) with minimum 8GB RAM - or equivalent
- Free disk space: approx. 7 GB

<br>

```

1. Download and install the Ollama desktop application
--------------------------------------------------------------

This is the link to download Ollama. After downloading, please install it on your computer.
Then launch it. A white chat window will open.
https://ollama.com/

Normally, Ollama will launch automatically when you start your computer.


2. Download an Ollama model
--------------------------------------------------------------

1. Open the Ollama desktop app.
2. Paste the model name (e.g. gemma3:270m) into the dropdown in the bottom right.
3. Type any message e.g. Hi, and press Enter
4. The model will start to auto download.

If you have a fast internet connection then I suggest you download
the gemma3:4b model (3.3GB).
This model can handle both text and images.
If you have a slow connection then download the smaller gemma3:270m model (292MB).
This model can handle text only.


3. Install ffmpeg
--------------------------------------------------------------

# on MacOS using Homebrew (https://brew.sh/)
brew install ffmpeg

# on Windows using Chocolatey (https://chocolatey.org/)
choco install ffmpeg

# on Windows using Scoop (https://scoop.sh/)
scoop install ffmpeg


4. Download the project folder and place it on your desktop
--------------------------------------------------------------

1. On GitHub click on "<> Code". The select "Download Zip"
2. Download the project folder and unzip it
3. Inside you will find a folder named: myOfflineAi-VoiceAssistant-v2.0
4. Place myOfflineAi-VoiceAssistant-v2.0 on your desktop.


5. Initial Setup
--------------------------------------------------------------

[ macOS ]
------------

(Skip steps 1-3 if you have uv already installed.)

1. Open Terminal (Command+Space, type "Terminal")
2. Paste this command into the terminal to install uv:

wget -qO- https://astral.sh/uv/install.sh | sh

3. Wait for uv installation to finish

4. Type 'cd ' in the terminal (with a space after cd)
5. Drag the folder into the Terminal window. A file path will appear.
6. Press Enter
If you get an error, then type in these commands in the terminal to manually cd into myOfflineAi-VoiceAssistant-v2.0 folder:
cd Desktop
cd myOfflineAi-VoiceAssistant-v2.0

7. Paste this command into the terminal:

cat start-mac-app.command > temp && mv temp start-mac-app.command && chmod +x start-mac-app.command

8. Press Enter
9. Open the myOfflineAi-VoiceAssistant-v2.0 folder
10. Double-click: start-mac-app.command


[ Windows ]
------------

(Skip steps 1-6 if you have uv already installed.)

1. Press the Windows key on your keyboard
2. Type cmd and press Enter (a black window will open)
3. Copy this entire command:

powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

4. Right-click in the black window to paste
5. Press Enter
6. Wait for "uv installed successfully" or similar message

7. Close the window and open a new one for the changes to take effect
8. Navigate to the myOfflineAi-VoiceAssistant-v2.0 folder that's on your desktop
9. Double-click: start-windows-app.bat

If Windows shows a security warning:
1. Right-click on start-windows-app.bat 
2. Select "Properties"
3. Check the "Unblock" box at the bottom
4. Click "OK"
5. Now double-click start-windows-app.bat to run


6. Use the app
--------------------------------------------------------------

Type a message. The assistant will respond with both voice and text.
To use voice input: Click the mic icon, then speak.

The name of the model you downloaded will appear in the dropdown menu in the top left.
If you downloaded the gemma3:4b model you can submit images and pdf documents in addition to text.

The app does not stop running when you close the browser tab.
To shut down the app simply close the terminal window.
You can also close the terminal by selecting it and typing Ctrl+C on Mac or Ctrl+C on Windows.


7. Future startup
--------------------------------------------------------------

Now that the setup is complete, in future simply Double-click a file to launch the app.
The project folder should be placed on your desktop before the app is launched.

Mac:
start-mac-app.command

Windows:
start-windows-app.bat

You could start the app and leave it running in the background all day.
Then whenever you want to use it, enter the following url in your browser:

http://127.0.0.1:5000/

Your browser will remember this local address so you won't have to.


Quick Troubleshooting
--------------------------------------------------------------
- If the app doesn't start, make sure Ollama is running (look for its icon in your system tray/menu bar)
- If you see "connection refused", restart Ollama
- Make sure you've downloaded at least one model in Ollama before using the app
- For the voice (TTS) to work Kokoro needs two files: kokoro-v1.0.onnx, and voices-v1.0.bin
  These files are auto downloaded during the setup process.
However, if the voice is not working then please download these files manually and place them in the project folder:
kokoro-v1.0.onnx: https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
voices-v1.0.bin: https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin



```
<br>

## Notes

- The latency (speed) will depend on your computer, the model size and the size of the context. I found that Gemma3:4b and Gemma3:12b give a good balance of speed and intelligence. They also support image input. The biggest factor is the Ollama inference time - the better your computer (faster GPU plus more RAM), the faster the inference time will be.
- In MacOS, Ollama models run on the internal GPU (via Metal). That's the magic behind Ollama. Kokoro-onnx is supposed to run on the internal NPU (via CoreML), but in my testing (M4 Macbook Air) this wasn't happening. It was running on the CPU instead - but it was still fast.<br>
- The chat history and user settings are saved to two files: voice_assistant_history.json, user_settings.json. These files can be found in the main project folder. You should delete these files or store them in a secure location - if you have privacy and security concerns.
- Whisper is capable of hallucination. Sometimes, when the user is silent, Whisper generates random text like, "Thank you for watching!"
- The app can freeze when you submit more than one image. This caused by a large amount of base64 image data being sent via WebSockets. This issue can be solved by implementing a hybrid HTTP and Websockets architecture. I've implemented that in this project:<br>
  https://github.com/vbookshelf/myOfflineAi-ChatConsole
- I've included detailed trouble-shooting info in the writeup for the original MyOfflineAi project. You can find it here:<br>
 https://github.com/vbookshelf/myOfflineAi-PrivacyFirst


<br>

## Resources

- openai-whisper<br>
https://pypi.org/project/openai-whisper/

- kokoro-onnx<br>
https://github.com/thewh1teagle/kokoro-onnx

- Kokoro Local TTS + Custom Voices<br>
Sam Witteveen<br>
https://www.youtube.com/watch?v=tl1wvZXlj0I

- hexgrad/Kokoro-82M<br>
  https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md

<br>

## App Family - Offline-First, Privacy-First, Transparent

- myOfflineAi-PrivacyFirst<br>(Maximum security. No chat history is saved.)<br>
  https://github.com/vbookshelf/myOfflineAi-PrivacyFirst<br>
- myOfflineAi-ChatHistory<br>(Saves chats to a local file you control.)<br>
  https://github.com/vbookshelf/myOfflineAi-ChatHistory<br>
- Chat-Image-Marker<br>(A simple, offline tool for marking up images.)<br>
  https://github.com/vbookshelf/Chat-Image-Marker<br>
- myOfflineAi-VoiceAssistant<br>(An offline full-featured Ai voice assistant.)<br>
  https://github.com/vbookshelf/myOfflineAi-VoiceAssistant<br>
-  myOfflineAi-ChatConsole<br>(Desktop multimodal chat console that supports both text chat and voice chat.)<br>
  https://github.com/vbookshelf/myOfflineAi-ChatConsole


<br>

## Revision History

Version 2.1<br>
27-Oct-2025<br>
Fixed error where Qwen models where not working.<br>
Removed model parameters that are not supported by all models.

Version 2.0<br>
18-Oct-2025<br>
Used WebSockets to implement sentence-by-sentence TTS to reduce audio delay.

Version 1.1<br>
15-Oct-2025<br>
Added webcam photo feature.

Version 1.0<br>
13-Oct-2025<br>
Prototype. Released for testing and education.


