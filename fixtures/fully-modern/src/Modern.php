<?php

declare(strict_types=1);

namespace Fixtures\FullyModern;

final readonly class Modern
{
    public function __construct(
        private string $label,
    ) {
    }

    public function label(): string
    {
        return $this->label;
    }
}
