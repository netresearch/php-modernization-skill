<?php

declare(strict_types=1);

/*
 * The PER coding style is planned, not configured:
 *   '@PER-CS3x0' => true,
 */
return (new PhpCsFixer\Config())->setRules([
    '@Symfony' => true, // '@PER-CS3x0' => true once the codebase is reformatted
]);
