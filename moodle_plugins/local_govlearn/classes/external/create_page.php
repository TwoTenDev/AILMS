<?php
namespace local_govlearn\external;

defined('MOODLE_INTERNAL') || die();
use core_external\external_api;
use core_external\external_function_parameters;
use core_external\external_single_structure;
use core_external\external_value;

class create_page extends external_api {

    public static function execute_parameters(): external_function_parameters {
        return new external_function_parameters([
            'courseid'   => new external_value(PARAM_INT, 'Course ID'),
            'sectionnum' => new external_value(PARAM_INT, 'Section number'),
            'name'       => new external_value(PARAM_TEXT, 'Page title'),
            'content'    => new external_value(PARAM_RAW, 'HTML content'),
            'visible'    => new external_value(PARAM_INT, 'Visible', VALUE_DEFAULT, 1),
        ]);
    }

    public static function execute(int $courseid, int $sectionnum, string $name, string $content, int $visible = 1): array {
        global $CFG;
        require_once($CFG->dirroot . '/course/lib.php');

        $params = self::validate_parameters(self::execute_parameters(), [
            'courseid'   => $courseid,
            'sectionnum' => $sectionnum,
            'name'       => $name,
            'content'    => $content,
            'visible'    => $visible,
        ]);

        $context = \context_course::instance($params['courseid']);
        self::validate_context($context);
        require_capability('moodle/course:manageactivities', $context);

        $moduleinfo = new \stdClass();
        $moduleinfo->modulename    = 'page';
        $moduleinfo->course        = $params['courseid'];
        $moduleinfo->section       = $params['sectionnum'];
        $moduleinfo->name          = $params['name'];
        $moduleinfo->content       = $params['content'];
        $moduleinfo->contentformat = FORMAT_HTML;
        $moduleinfo->introeditor   = ['text' => '', 'format' => FORMAT_HTML, 'itemid' => 0];
        $moduleinfo->visible       = $params['visible'];

        $moduleinfo = create_module($moduleinfo);

        return [
            'cmid'       => (int) $moduleinfo->coursemodule,
            'sectionnum' => $params['sectionnum'],
        ];
    }

    public static function execute_returns(): external_single_structure {
        return new external_single_structure([
            'cmid'       => new external_value(PARAM_INT, 'Course module ID'),
            'sectionnum' => new external_value(PARAM_INT, 'Section number'),
        ]);
    }
}
