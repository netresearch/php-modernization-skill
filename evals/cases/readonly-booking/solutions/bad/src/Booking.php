<?php

declare(strict_types=1);

namespace Cases\ReadonlyBooking;

final readonly class Booking
{
    public function __construct(private \DateTime $start, private string $room)
    {
    }

    public function start(): \DateTimeInterface
    {
        return $this->start;
    }

    public function room(): string
    {
        return $this->room;
    }
}
