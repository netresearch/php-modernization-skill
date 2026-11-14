<?php

declare(strict_types=1);

namespace Cases\ReviewReadonlyReschedule;

final class Booking
{
    private \DateTime $start;
    private Room $room;
    private Guest $guest;

    public function __construct(\DateTime $start, Room $room, Guest $guest)
    {
        $this->start = $start;
        $this->room = $room;
        $this->guest = $guest;
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
