<?php
namespace local_govlearn\external;

defined('MOODLE_INTERNAL') || die();

use core_external\external_api;
use core_external\external_function_parameters;
use core_external\external_multiple_structure;
use core_external\external_single_structure;
use core_external\external_value;

class create_quiz extends external_api {

    public static function execute_parameters(): external_function_parameters {
        return new external_function_parameters([
            'courseid'   => new external_value(PARAM_INT, 'Course ID'),
            'sectionnum' => new external_value(PARAM_INT, 'Section number'),
            'name'       => new external_value(PARAM_TEXT, 'Quiz name', VALUE_DEFAULT, 'Knowledge Check'),
            'intro'      => new external_value(PARAM_RAW, 'Quiz introduction HTML', VALUE_DEFAULT, ''),
            'questions'  => new external_multiple_structure(
                new external_single_structure([
                    'questiontext' => new external_value(PARAM_RAW, 'Question text'),
                    'optiona'      => new external_value(PARAM_RAW, 'Option A'),
                    'optionb'      => new external_value(PARAM_RAW, 'Option B'),
                    'optionc'      => new external_value(PARAM_RAW, 'Option C'),
                    'optiond'      => new external_value(PARAM_RAW, 'Option D'),
                    'correct'      => new external_value(PARAM_ALPHA, 'Correct answer letter (A-D)'),
                    'explanation'  => new external_value(PARAM_RAW, 'Answer explanation'),
                ])
            ),
        ]);
    }

    public static function execute(int $courseid, int $sectionnum, string $name, string $intro, array $questions): array {
        global $CFG, $DB;

        require_once($CFG->dirroot . '/course/lib.php');
        require_once($CFG->dirroot . '/mod/quiz/lib.php');
        require_once($CFG->dirroot . '/mod/quiz/locallib.php');

        $params = self::validate_parameters(self::execute_parameters(), [
            'courseid'   => $courseid,
            'sectionnum' => $sectionnum,
            'name'       => $name,
            'intro'      => $intro,
            'questions'  => $questions,
        ]);

        $context = \context_course::instance($params['courseid']);
        self::validate_context($context);
        require_capability('moodle/course:manageactivities', $context);

        // Create the quiz activity
        $moduleinfo                      = new \stdClass();
        $moduleinfo->modulename          = 'quiz';
        $moduleinfo->course              = $params['courseid'];
        $moduleinfo->section             = $params['sectionnum'];
        $moduleinfo->name                = $params['name'];
        $moduleinfo->introeditor         = ['text' => $params['intro'], 'format' => FORMAT_HTML, 'itemid' => 0];
        $moduleinfo->visible             = 1;
        $moduleinfo->grade               = 100;
        $moduleinfo->attempts            = 0;
        $moduleinfo->grademethod         = 1;
        $moduleinfo->shuffleanswers      = 1;
        $moduleinfo->preferredbehaviour  = 'deferredfeedback';
        $moduleinfo->quizpassword        = '';

        $moduleinfo = create_module($moduleinfo);
        $cmid = (int) $moduleinfo->coursemodule;

        $cm   = get_coursemodule_from_id('quiz', $cmid, $params['courseid'], false, MUST_EXIST);
        $quiz = $DB->get_record('quiz', ['id' => $cm->instance], '*', MUST_EXIST);

        // Use module context for question category
        $modcontext = \context_module::instance($cmid);
        $category   = question_get_default_category($modcontext->id, true);

        $questioncount = 0;
        $letters = ['A' => 'optiona', 'B' => 'optionb', 'C' => 'optionc', 'D' => 'optiond'];

        foreach ($params['questions'] as $q) {
            // Insert question record directly to avoid file-handling issues in web service context
            $questionid = $DB->insert_record('question', (object)[
                'category'              => $category->id,
                'parent'                => 0,
                'name'                  => \core_text::substr($q['questiontext'], 0, 255),
                'questiontext'          => $q['questiontext'],
                'questiontextformat'    => FORMAT_HTML,
                'generalfeedback'       => '',
                'generalfeedbackformat' => FORMAT_HTML,
                'defaultmark'           => 1,
                'penalty'               => 0.3333333,
                'qtype'                 => 'multichoice',
                'length'                => 1,
                'stamp'                 => make_unique_id_code(),
                'version'               => make_unique_id_code(),
                'hidden'                => 0,
                'timecreated'           => time(),
                'timemodified'          => time(),
                'createdby'             => 2,
                'modifiedby'            => 2,
                'idnumber'              => null,
            ]);

            // Insert multichoice options
            $DB->insert_record('qtype_multichoice_options', (object)[
                'questionid'                     => $questionid,
                'layout'                         => 0,
                'single'                         => 1,
                'shuffleanswers'                 => 1,
                'correctfeedback'                => '',
                'correctfeedbackformat'          => FORMAT_HTML,
                'partiallycorrectfeedback'       => '',
                'partiallycorrectfeedbackformat' => FORMAT_HTML,
                'incorrectfeedback'              => '',
                'incorrectfeedbackformat'        => FORMAT_HTML,
                'answernumbering'                => 'abc',
                'shownumcorrect'                 => 0,
                'showstandardinstruction'        => 0,
            ]);

            // Insert answers
            foreach ($letters as $letter => $field) {
                $iscorrect = (strtoupper($q['correct']) === $letter);
                $DB->insert_record('question_answers', (object)[
                    'question'       => $questionid,
                    'answer'         => $q[$field],
                    'answerformat'   => FORMAT_HTML,
                    'fraction'       => $iscorrect ? 1.0 : 0.0,
                    'feedback'       => $iscorrect ? $q['explanation'] : '',
                    'feedbackformat' => FORMAT_HTML,
                ]);
            }

            // Link question to question bank
            $bankentryid = $DB->insert_record('question_bank_entries', (object)[
                'questioncategoryid' => $category->id,
                'idnumber'           => null,
                'ownerid'            => 2,
            ]);

            $DB->insert_record('question_versions', (object)[
                'questionbankentryid' => $bankentryid,
                'version'             => 1,
                'questionid'          => $questionid,
                'status'              => 'ready',
            ]);

            // Add question to quiz
            quiz_add_quiz_question($questionid, $quiz, 0, 1);
            $questioncount++;
        }

        return [
            'cmid'          => $cmid,
            'sectionnum'    => $params['sectionnum'],
            'questioncount' => $questioncount,
        ];
    }

    public static function execute_returns(): external_single_structure {
        return new external_single_structure([
            'cmid'          => new external_value(PARAM_INT, 'Course module ID'),
            'sectionnum'    => new external_value(PARAM_INT, 'Section number'),
            'questioncount' => new external_value(PARAM_INT, 'Number of questions added'),
        ]);
    }
}
