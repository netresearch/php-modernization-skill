<?php

declare(strict_types=1);

$EM_CONF[$_EXTKEY] = [
    'title' => 'Fixture: TYPO3 Extension Minimal',
    'description' => 'Synthetic TYPO3 extension fixture for verifier regression tests.',
    'category' => 'plugin',
    'state' => 'stable',
    'version' => '0.0.0',
    'constraints' => [
        'depends' => [
            'typo3' => '13.4.0-13.99.99',
        ],
    ],
];
