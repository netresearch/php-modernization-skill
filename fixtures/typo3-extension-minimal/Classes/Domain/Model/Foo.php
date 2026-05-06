<?php

declare(strict_types=1);

namespace Fixtures\Typo3ExtensionMinimal\Domain\Model;

final class Foo
{
    public function __construct(
        private readonly string $name,
    ) {
    }

    public function getName(): string
    {
        return $this->name;
    }
}
