<?php

declare(strict_types=1);

namespace Cases\ReadonlyBooking;

final class Booking
{
    private readonly \DateTime $start;

    public function __construct(\DateTime $start, private readonly string $room)
    {
        $this->start = clone $start;
    }

    public function start(): \DateTimeInterface
    {
        return clone $this->start;
    }

    public function room(): string
    {
        return $this->room;
    }
}
