<?php

declare(strict_types=1);

namespace Cases\ReviewReadonlyReschedule;

final readonly class Room
{
    public function __construct(private string $number, private int $capacity)
    {
    }

    public function number(): string
    {
        return $this->number;
    }

    public function capacity(): int
    {
        return $this->capacity;
    }
}
