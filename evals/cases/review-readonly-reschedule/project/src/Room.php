<?php

declare(strict_types=1);

namespace Cases\ReviewReadonlyReschedule;

final class Room
{
    private string $number;
    private int $capacity;

    public function __construct(string $number, int $capacity)
    {
        $this->number = $number;
        $this->capacity = $capacity;
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
