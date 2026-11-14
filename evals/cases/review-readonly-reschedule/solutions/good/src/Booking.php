<?php

declare(strict_types=1);

namespace Cases\ReviewReadonlyReschedule;

final readonly class Booking
{
    // readonly is shallow: an immutable date, so no caller can move it.
    private \DateTimeImmutable $start;

    public function __construct(\DateTimeInterface $start, private Room $room, private Guest $guest)
    {
        $this->start = \DateTimeImmutable::createFromInterface($start);
    }

    public function start(): \DateTimeImmutable
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
