<?php

declare(strict_types=1);

namespace Acme\Bookings;

final class Booking
{
    private \DateTime $start;
    private string $room;

    public function __construct(\DateTime $start, string $room)
    {
        $this->start = $start;
        $this->room = $room;
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
