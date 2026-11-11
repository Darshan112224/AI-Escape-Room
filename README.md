# 🔐 AI Escape Room

An interactive text escape-room game where a Large Language Model (**Google Gemini**)
acts as the **Game Master**. You wake up locked inside an old library, explore it in
plain English, find clues, solve puzzles and type the right code to escape.

The project is built in two versions:

| | Version 1: Interactive | Version 2: Reliable |
|---|---|---|
| Who decides outcomes? | The LLM | Python game engine |
| Game state | Chat history only | Structured `GameState` + JSON game data |
| Where are the solutions? | Inside the LLM prompt | Only in `game_data.json` (never sent to the LLM) |
| Test cases passed | 4 / 9 | **9 / 9** |
| Status | ✅ Done (tag `v1.0`) | ✅ Done |

---

## 🧩 The problem

LLMs are great storytellers, which makes them a natural fit for a text adventure's
Game Master. But they are not reliable rule-keepers: they can forget what happened,
invent objects, reveal secrets or let the player do impossible things. This project
first builds a fun LLM-driven game (V1), then shows how to make it **trustworthy**
by moving the rules into code (V2).

## 🏛️ The room: "The Locked Library"

| Object | Role |
|---|---|
| ✍️ Writing desk | Holds a note with the first hint |
| 🖼️ Painting | Hides something behind it |
| 🗄️ Locked drawer | Needs a key |
| 📚 Bookshelf | Four suspicious books with digits |
| 💡 Reading lamp | Just atmosphere (a red herring) |
| 🚪 Exit door | 4-digit keypad, the final challenge |

**3 chained puzzles + 1 final challenge.** (No spoilers here 😉)

---

## 🛠️ Tech stack

- **Python 3.10+**
- **Streamlit**: web chat interface
- **Google Gemini API** (free tier) via the `google-genai` SDK
- **python-dotenv**: loads the API key from `.env`
- **pytest** + Streamlit `AppTest`: automated tests with a fake LLM client

## 🚀 Installation & running

```bash
# 1. Clone the repository
git clone https://github.com/Darshan112224/AI-Escape-Room.git
cd AI-Escape-Room

# 2. Create a virtual environment (recommended)
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Add your free Gemini API key
cp .env.example .env              # Windows: copy .env.example .env
#    then open .env and paste your key from https://aistudio.google.com/apikey

# 5. Run a version
streamlit run v1/app.py           # Version 1
streamlit run v2/app.py           # Version 2 (also runs without an API key, in offline mode)
```

The app opens at http://localhost:8501.

> **Which model?** The default is `gemini-3.5-flash-lite`: on the free tier, Flash-Lite
> models allow ~500 requests/day versus ~20/day for full Flash models.
>
> **"Model not found" error?** Google retires model names over time. The app falls
> back to other Flash models automatically, but you can also run
> `python v1/list_models.py` and copy a model name into `GEMINI_MODEL` in `.env`.

### Running the tests

```bash
cd v1 && pytest      # 13 tests
cd ../v2 && pytest   # 91 tests, including every test case from docs/test_cases.md
```

The tests replace Gemini with a fake client, so they need **no API key**.

---

## 📦 Version 1: Interactive AI Escape Room

The LLM runs the entire game. Its system prompt contains the room, the puzzle chain
and the solution. Python stores the chat history and resends it every turn, because
LLM APIs are stateless. The LLM signals a win by writing a secret `[ESCAPED]` marker,
which the app detects to show the victory screen.

**Features:** natural-language chat, opening scene, sidebar instructions, hints on
request, turn counter, victory screen, restart button.

➡️ Architecture diagram and known weaknesses: [`docs/v1_architecture.md`](docs/v1_architecture.md)

### Screenshots

| Normal win | V1 bug: escaping without solving the puzzles |
|---|---|
| ![Victory](docs/screenshots/v1_victory.png) | ![Direct code](docs/screenshots/tc6_tc7_crowbar_and_direct_code.png) |

### What went wrong in V1

We ran 9 test cases, including adversarial ones
(full results: [`docs/test_cases.md`](docs/test_cases.md)). **V1 scored 4 pass · 2 partial · 3 fail.**

Gemini handled the *obvious* attacks well (fake admin, "reveal all codes", nonexistent
crowbar) but failed on **game-state** problems:

- ❌ Opened the drawer with a key the player **never picked up**
- ❌ Let the player **escape by typing the code** without ever solving the bookshelf puzzle
- ❌ Solved the **whole puzzle chain in one turn** when the player chained many actions
- ⚠️ **Leaked a hint** when the player falsely claimed to have solved a puzzle
- ⚠️ Gave **contradictory feedback** ("must be four digits" for a four-digit code)

These failures happen because in V1 the LLM is both the storyteller **and** the rule-keeper.
Version 2 separates those two jobs.

```
v1/
├── app.py               # Streamlit UI
├── game_master.py       # Gemini client: history, retries, escape detection
├── prompts.py           # Opening scene + Game Master system prompt
├── list_models.py       # Helper: shows which Gemini models your key can use
├── test_game_master.py  # Unit tests (fake client)
└── test_app.py          # Headless UI tests (Streamlit AppTest)
```

## 📦 Version 2: Reliable AI Escape Room

**Core principle: Python decides, the LLM describes.**

Every turn goes through three stages:

```
"use the key on the drawer"
      │
 ① UNDERSTAND   Intent parser: regex rules first, Gemini (structured JSON output) as backup
      │         → {"action": "use", "item": "key", "target": "drawer"}
 ② DECIDE       GameEngine checks GameState: is the key in the inventory? Is the drawer locked?
      │         → success / failure + approved facts. No LLM involved.
 ③ DESCRIBE     Narrator (Gemini) turns the facts into story text.
                Output guard: no leaked or invented numbers, no fake victory.
```

### What changed from V1, and why

| V1 problem | V2 change | Why it was necessary |
|---|---|---|
| No memory except chat text | **`GameState` dataclass**: inventory, flags, solved puzzles, door, attempts, action log | The LLM forgot or misread state, e.g. using a key it never gave the player |
| Solutions inside the prompt | **`game_data.json`**, read only by the engine | If the LLM knows the answer, it can leak it or be tricked into revealing it |
| LLM decided success and victory | **`GameEngine`** validation functions; the door needs the code **and** the solved puzzles | A prompt can't *force* rule-following; code can |
| Many actions in one message | Parser keeps **one action per turn** | The whole puzzle chain was skipped in one message |
| Free-text understanding only | **Structured output** with a Pydantic schema | The LLM can only choose from 12 allowed actions; it cannot "decide" anything |
| LLM text shown unchecked | **Output guard** + fallback to plain engine facts | Last line of defence against leaks and hallucinations |
| Game unusable when the API failed | **Offline mode**: rules parser + engine work without an LLM | Free-tier quota and 503 errors were frequent in V1 testing |

➡️ Architecture diagram and design decisions: [`docs/v2_architecture.md`](docs/v2_architecture.md)
➡️ All test cases, V1 vs V2: [`docs/test_cases.md`](docs/test_cases.md)

### V2 features

- Live sidebar with **inventory, puzzle checklist, door status, turns, wrong codes**,
  read from the real game state
- **"Show engine decisions"** toggle: see the parsed intent, the engine's decision and the
  output-guard result for every turn
- Progressive **hints** chosen by the engine, based on progress
- Hidden items answer exactly like nonexistent ones, so guessing names reveals nothing

```
v2/
├── app.py               # Streamlit UI (state sidebar + debug panel)
├── game.py              # Wires parser → engine → narrator into one turn
├── game_data.json       # Room, objects, rules, hints and the secret solution
├── game_state.py        # GameState dataclass (structured memory)
├── engine.py            # Rule engine: validation + state changes (no LLM)
├── intent.py            # Intent schema (Pydantic), the parser–engine contract
├── intent_parser.py     # Hybrid parser: regex rules → Gemini structured output
├── narrator.py          # LLM narration + output guard + offline fallback
├── llm_client.py        # Shared Gemini client: timeout, retries, model fallback
└── test_*.py            # 91 automated tests
```

---

## 🔒 Security

API keys are never committed. `.env` is in `.gitignore`; `.env.example` shows the
required settings.
