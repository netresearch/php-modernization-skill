<?php

declare(strict_types=1);

// The shared ruleset of netresearch/typo3-ci-workflows. Its rules.php enables
// the PER coding style; this file names no ruleset itself.
$createConfig = require __DIR__ . '/.Build/vendor/netresearch/typo3-ci-workflows/config/php-cs-fixer/config.php';

return $createConfig('', __DIR__);
