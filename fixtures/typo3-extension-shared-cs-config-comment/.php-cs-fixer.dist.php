<?php

declare(strict_types=1);

/*
 * Usage example copied from netresearch/typo3-ci-workflows; this file does
 * not follow it and configures its own rules:
 *
 *   $createConfig = require __DIR__ . '/.Build/vendor/netresearch/typo3-ci-workflows/config/php-cs-fixer/config.php';
 */
// $createConfig = require __DIR__ . '/.Build/vendor/netresearch/typo3-ci-workflows/config/php-cs-fixer/config.php';

return (new PhpCsFixer\Config())
    ->setRules(['@Symfony' => true]);
