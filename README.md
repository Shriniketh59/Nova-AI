# 🤖 NovaAI

<div align="center">

![AI](https://img.shields.io/badge/Artificial%20Intelligence-Powered-blue)
![Python](https://img.shields.io/badge/Python-3.x-yellow)
![Machine Learning](https://img.shields.io/badge/Machine-Learning-success)
![Status](https://img.shields.io/badge/Status-Development-orange)

### An Intelligent AI Platform for Smart Automation & Productivity

*"Empowering users with Artificial Intelligence to solve real-world problems efficiently."*

</div>

---

# 📖 Overview

NovaAI is an Artificial Intelligence platform designed to provide intelligent solutions through Machine Learning, Natural Language Processing, Data Analytics, and Generative AI technologies.

The objective of NovaAI is to simplify complex tasks, automate workflows, and provide users with AI-powered insights through an intuitive interface.

This project demonstrates the integration of AI models with modern software engineering practices to build scalable and efficient intelligent applications.

---

# 🎯 Objectives

- Develop an intelligent AI assistant
- Automate repetitive tasks
- Perform intelligent data analysis
- Generate AI-powered responses
- Provide real-time decision support
- Learn and implement modern AI technologies

---

# ✨ Features

- 🤖 AI-powered assistant
- 💬 Natural Language Processing
- 📊 Intelligent Data Analytics
- 🧠 Machine Learning Integration
- 📈 Predictive Analytics
- 🔍 Smart Search
- ⚡ Fast Response System
- 🔐 Secure Authentication
- ☁️ Cloud Ready Architecture
- 📱 Responsive User Interface

---

# 🛠️ Tech Stack

## Programming Languages

- Python
- JavaScript
- HTML
- CSS
- SQL

## AI & Machine Learning

- Machine Learning
- Deep Learning
- Natural Language Processing
- Generative AI

## Frameworks

- Flask / FastAPI *(Based on implementation)*
- TensorFlow
- Scikit-learn

## Database

- MySQL / SQLite

## Tools

- Git
- GitHub
- VS Code
- Jupyter Notebook

---

# 📂 Project Structure

```
NovaAI
│
├── data/
├── models/
├── notebooks/
├── static/
├── templates/
├── api/
├── app.py
├── requirements.txt
├── README.md
└── LICENSE
```

---

# 🚀 Installation

Clone the repository

```bash
git clone https://github.com/Shriniketh59/Nova-AI.git
```

Go inside the project

```bash
cd Nova-AI
```

Install dependencies

```bash
pip install -r requirements.txt
```

Run

```bash
python app.py
```

---

# 🔊 Voice Setup

Nova's voice pipeline is **100% local and offline**. No cloud speech service is
used at any point — not for speech recognition, not for speech synthesis.

| Stage | Engine | Runs |
|-------|--------|------|
| Speech-to-text | `faster-whisper` | Locally (Python package) |
| Reasoning | Ollama (`llama3.2:3b`) | Locally |
| Text-to-speech | `pyttsx3` | Locally, via a **system speech engine** |

### Required: install a system speech engine

`pyttsx3` does not ship voices of its own — it drives whatever speech engine
your OS provides. **Text-to-speech will not work until one is installed.**

```bash
# Debian / Ubuntu
sudo apt install espeak-ng

# Fedora / RHEL
sudo dnf install espeak-ng

# Arch
sudo pacman -S espeak-ng

# macOS — NSSpeechSynthesizer is built in, nothing to install
# Windows — SAPI5 is built in, nothing to install
```

If no engine or voice is found, Nova does **not** crash or fail silently: the
voice session reports an explicit `tts_unavailable` error through the voice
state machine, and `GET /api/voice/config` returns `ttsAvailable: false` with
the reason in `ttsError`. Text chat is unaffected.

### Voice selection

By default Nova enumerates the installed voices at startup and automatically
picks the best available **English** voice, preferring **en-GB** and preferring
a **male** voice. Nothing is hardcoded, so a voice that is not installed on your
host is never requested.

To pin a specific voice, set `TTS_VOICE_ID` — this skips auto-detection
entirely:

```bash
# List the voice ids available on this machine
python -c "import pyttsx3; [print(v.id, '|', v.name) for v in pyttsx3.init().getProperty('voices')]"

# Then pin one
export TTS_VOICE_ID="english-gb"
```

Other tunables: `TTS_RATE` (words per minute, default `165`) and `TTS_VOLUME`
(`0.0`–`1.0`, default `1.0`).

---

# 🗂️ Vector Database

Nova uses **ChromaDB** as its vector store — embedded and persistent, with no
separate server process, no network access and no API key.

The index lives at `server/data/chroma` by default; override with `CHROMA_PATH`.

Qdrant remains fully implemented and selectable for deployments that already
run it:

```bash
export VECTOR_STORE_BACKEND=qdrant
export QDRANT_URL=http://localhost:6333
```

> **Note:** switching backends does not migrate existing vectors. Documents
> indexed under one backend must be re-indexed to appear under the other.

---

# 📊 Applications

NovaAI can be applied in

- Education
- Healthcare
- Finance
- Customer Support
- Business Intelligence
- Automation
- Data Analytics
- Research

---

# 🎯 Future Scope

- Voice Assistant
- AI Chatbot
- Image Generation
- Document Analysis
- Multilingual Support
- Cloud Deployment
- Mobile Application
- Enterprise Integration

---

# 📸 Screenshots

Add project screenshots here.

```
Home Page

Dashboard

AI Response

Analytics
```

---

# 📈 Roadmap

- [x] Project Planning
- [x] Initial Development
- [ ] AI Model Integration
- [ ] Backend Development
- [ ] Frontend Enhancement
- [ ] Cloud Deployment
- [ ] Production Release

---

# 🤝 Contributing

Contributions are welcome.

Fork the repository.

Create your feature branch.

Commit your changes.

Submit a Pull Request.

---

# 👨‍💻 Author

**Shri Niketh**

B.Tech Artificial Intelligence & Data Science

GitHub:
https://github.com/Shriniketh59

LinkedIn:
https://www.linkedin.com/in/shri-niketh-2337b0358

---

# ⭐ Support

If you found this project useful, consider giving it a ⭐ on GitHub.

It motivates further development.

---

# 📄 License

This project is licensed under the MIT License.
