<?php

declare(strict_types=1);

namespace Cases\ReviewReadonlyReschedule;

final readonly class Booking
{
    public function __construct(private \DateTime $start, private Room $room, private Guest $guest)
    {
    }

    public function start(): \DateTime
    {
        return $this->start;
    }

    public function room(): Room
    {
        return $this->room;
    }

    public function guest(): Guest
    {
        return $this->guest;
    }
}
