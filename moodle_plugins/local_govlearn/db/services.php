<?php
defined('MOODLE_INTERNAL') || die();

$functions = [
    'local_govlearn_create_page' => [
        'classname'    => 'local_govlearn\external\create_page',
        'methodname'   => 'execute',
        'description'  => 'Create a page module in a course section',
        'type'         => 'write',
        'capabilities' => 'moodle/course:manageactivities',
        'services'     => [MOODLE_OFFICIAL_MOBILE_SERVICE],
    ],
    'local_govlearn_create_quiz' => [
        'classname'    => 'local_govlearn\external\create_quiz',
        'methodname'   => 'execute',
        'description'  => 'Create a quiz with questions in a course section',
        'type'         => 'write',
        'capabilities' => 'moodle/course:manageactivities',
        'services'     => [MOODLE_OFFICIAL_MOBILE_SERVICE],
    ],
];
