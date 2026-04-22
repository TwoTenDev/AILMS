# GovLearn Moodle Plugin — Claude Code Spec

## Overview

Build a Moodle local plugin (`local_govlearn`) that exposes REST web service functions for programmatic course content creation. This plugin is part of the GovLearn AILMS stack and is installed inside the Moodle container at deploy time.

The plugin replaces the need for PHP CLI hacks or deprecated Moodle APIs. Once installed, `create_moodle_course.py` calls these clean REST endpoints to build full courses from `knowledge_base.json`.

---

## Repository Context

- **Repo:** `git@github.com:TwoTenDev/AILMS.git`
- **Branch:** `develop`
- **Working dir:** `~/AILMS`
- **Stack:** Docker Compose on VM `192.168.122.153`
- **Moodle container:** `ailms-moodle-1`
- **Moodle root inside container:** `/bitnami/moodle/public`
- **Plugin will live at:** `/bitnami/moodle/public/local/govlearn/`
- **On host, plugin source goes in:** `~/AILMS/moodle_plugins/local_govlearn/`

---

## Step 1: Create the Plugin File Structure

Create the following files under `~/AILMS/moodle_plugins/local_govlearn/`:

```
local_govlearn/
├── db/
│   └── services.php        # Register web service functions
├── lang/
│   └── en/
│       └── local_govlearn.php  # Language strings
├── classes/
│   └── external/
│       ├── create_page.php     # Create a page module in a course
│       └── create_quiz.php     # Create a quiz with questions
└── version.php             # Plugin version and metadata
```

---

## Step 2: File Contents

### `version.php`

```php
<?php
defined('MOODLE_INTERNAL') || die();

$plugin->component = 'local_govlearn';
$plugin->version   = 2025042200;
$plugin->requires  = 2024100700; // Moodle 4.5+
$plugin->maturity  = MATURITY_STABLE;
$plugin->release   = '1.0.0';
```

---

### `lang/en/local_govlearn.php`

```php
<?php
defined('MOODLE_INTERNAL') || die();

$string['pluginname'] = 'GovLearn Web Services';
$string['govlearn:manage'] = 'Manage GovLearn content';
```

---

### `db/services.php`

Register two web service functions: `local_govlearn_create_page` and `local_govlearn_create_quiz`.

```php
<?php
defined('MOODLE_INTERNAL') || die();

$functions = [
    'local_govlearn_create_page' => [
        'classname'   => 'local_govlearn\external\create_page',
        'methodname'  => 'execute',
        'description' => 'Create a page module in a course section',
        'type'        => 'write',
        'capabilities'=> 'moodle/course:manageactivities',
        'services'    => [MOODLE_OFFICIAL_MOBILE_SERVICE],
    ],
    'local_govlearn_create_quiz' => [
        'classname'   => 'local_govlearn\external\create_quiz',
        'methodname'  => 'execute',
        'description' => 'Create a quiz with questions in a course section',
        'type'        => 'write',
        'capabilities'=> 'moodle/course:manageactivities',
        'services'    => [MOODLE_OFFICIAL_MOBILE_SERVICE],
    ],
];
```

---

### `classes/external/create_page.php`

This function creates a Moodle `page` module (rich HTML content page) in a given course section.

Parameters:
- `courseid` (int) — Moodle course ID
- `sectionnum` (int) — Section number (0 = general, 1 = first topic, etc.)
- `name` (string) — Page title
- `content` (string) — HTML content for the page body
- `visible` (int, default 1) — Whether the page is visible

Implementation notes:
- Use `course_create_module()` from `course/lib.php` (include it via `require_once($CFG->dirroot.'/course/lib.php')`)
- The module data object needs: `modulename`, `course`, `section`, `name`, `content`, `contentformat` (1=HTML), `visible`
- Validate context using `context_course::instance($courseid)` and `self::validate_context()`
- Require capability `moodle/course:manageactivities`
- Return the new course module id (`cmid`) and section number

Returns:
```json
{"cmid": 123, "sectionnum": 1}
```

---

### `classes/external/create_quiz.php`

This function creates a Moodle `quiz` module and adds multiple choice questions to it.

Parameters:
- `courseid` (int) — Moodle course ID
- `sectionnum` (int) — Section number
- `name` (string) — Quiz title (default: "Knowledge Check")
- `intro` (string) — Quiz introduction HTML
- `questions` (array) — Array of question objects, each with:
  - `questiontext` (string) — The question text
  - `optiona` (string) — Option A text
  - `optionb` (string) — Option B text
  - `optionc` (string) — Option C text
  - `optiond` (string) — Option D text
  - `correct` (string) — Correct answer letter: "A", "B", "C", or "D"
  - `explanation` (string) — Feedback shown after answering

Implementation notes:
- Create the quiz module using `course_create_module()` with `modulename = 'quiz'`
- Quiz module data needs: `course`, `section`, `name`, `intro`, `introformat` (1), `visible` (1), `grade` (100), `attempts` (0 = unlimited)
- For each question, use the question bank API:
  - `require_once($CFG->dirroot.'/question/lib.php')`
  - `require_once($CFG->dirroot.'/question/engine/lib.php')`
  - Create a `stdClass` question object with `qtype = 'multichoice'`
  - Set `category` to the course default question category (fetch via `question_get_default_category($context->id, true)`)
  - Set `name`, `questiontext`, `questiontextformat` (1), `generalfeedback` (''), `defaultmark` (1), `penalty` (0.3333333), `hidden` (0)
  - For multichoice: set `single` (1), `shuffleanswers` (1), `answernumbering` ('abc'), `correctfeedback` (''), `partiallycorrectfeedback` (''), `incorrectfeedback` ('')
  - Add answers array: each answer has `answer` (text), `answerformat` (1), `fraction` (1.0 for correct, 0 for wrong), `feedback` (''), `feedbackformat` (1)
  - Save question using `question_bank::get_qtype('multichoice')->save_question($question, $question)`
  - Add question to quiz using `quiz_add_quiz_question($question->id, $quiz_instance, $sectionnum, 1)`
- Require includes: `mod/quiz/locallib.php`, `mod/quiz/lib.php`

Returns:
```json
{"cmid": 456, "sectionnum": 2, "questioncount": 5}
```

---

## Step 3: Register Functions in the DB

After creating the plugin files, register them in Moodle by adding to `mdl_external_services_functions`:

```sql
INSERT INTO mdl_external_services_functions (externalserviceid, functionname)
VALUES
  (1, 'local_govlearn_create_page'),
  (1, 'local_govlearn_create_quiz')
ON CONFLICT DO NOTHING;
```

Where `externalserviceid = 1` is the Moodle mobile web service.

---

## Step 4: Install the Plugin into the Container

Copy the plugin into the Moodle container and run the upgrade CLI:

```bash
# Copy plugin files into container
docker cp ~/AILMS/moodle_plugins/local_govlearn ailms-moodle-1:/bitnami/moodle/public/local/govlearn

# Run Moodle upgrade to register the plugin
docker exec -it ailms-moodle-1 php /bitnami/moodle/public/admin/cli/upgrade.php --non-interactive
```

---

## Step 5: Add to docker-compose.yml

So the plugin persists across container rebuilds, mount it as a volume in `docker-compose.yml`:

```yaml
moodle:
  volumes:
    - ./moodle_plugins/local_govlearn:/bitnami/moodle/public/local/govlearn
```

Add this under the existing `moodle` service volumes section.

---

## Step 6: Update create_moodle_course.py

Update `~/AILMS/chatbot/create_moodle_course.py` to replace the broken `core_course_edit_module` calls with the new plugin functions:

### Replace `add_page()`:
```python
def add_page(course_id: int, section: int, title: str, content: str) -> dict:
    html = markdown_to_html(content)
    return call(
        "local_govlearn_create_page",
        courseid=course_id,
        sectionnum=section,
        name=title,
        content=html,
        visible=1,
    )
```

### Replace `create_quiz()`:
```python
def create_quiz(course_id: int, section: int, module_id: str, questions: list) -> dict:
    if not questions:
        print("  ⚠ No questions parsed, skipping.")
        return {}

    api_questions = []
    for q in questions:
        api_questions.append({
            "questiontext": q["question"],
            "optiona": q["options"].get("A", ""),
            "optionb": q["options"].get("B", ""),
            "optionc": q["options"].get("C", ""),
            "optiond": q["options"].get("D", ""),
            "correct": q["correct"],
            "explanation": q["explanation"],
        })

    # Flatten questions array for form encoding
    params = {
        "courseid": course_id,
        "sectionnum": section,
        "name": "Knowledge Check",
        "intro": "<p>Test your understanding of the module content.</p>",
    }
    for i, q in enumerate(api_questions):
        for key, val in q.items():
            params[f"questions[{i}][{key}]"] = val

    return call("local_govlearn_create_quiz", **params)
```

---

## Step 7: Test End-to-End

```bash
# Inside the chatbot container
docker exec -it ailms-chatbot-1 python generate_content.py --pdf cyber_policy.pdf --module-id cyber-101
docker exec -it ailms-chatbot-1 python create_moodle_course.py --kb knowledge_base.json --module-id cyber-101
```

Expected output:
```
🎓 GovLearn Moodle Course Builder
Step 1: Creating course... ✓
Step 2: Adding content pages...
  ✓ Page added (6 pages)
Step 3: Adding quiz...
  ✓ Quiz created (5 questions)
✅ Course built successfully!
   URL: http://192.168.122.153:8080/course/view.php?id=X
```

Then open the URL in a browser and verify:
- Course visible in Moodle
- All 6 content sections appear as pages
- Quiz section has 5 questions with correct answers

---

## Notes for Claude Code

- All PHP files must have `defined('MOODLE_INTERNAL') || die();` as the second line after `<?php`
- Use Moodle's external API pattern: `execute_parameters()`, `execute()`, `execute_returns()` as static methods
- Import external API classes: `use core_external\external_api`, `use core_external\external_function_parameters`, etc.
- Always call `self::validate_context()` before any DB operations
- The `course_create_module()` function handles section assignment automatically when `section` is set on the module object
- Test each function individually with curl before running the full pipeline
- If `upgrade.php` fails, check `/bitnami/moodle/public/local/govlearn/version.php` is valid PHP
- Moodle caches web service definitions — if functions don't appear after upgrade, run: `php admin/cli/purge_caches.php`
