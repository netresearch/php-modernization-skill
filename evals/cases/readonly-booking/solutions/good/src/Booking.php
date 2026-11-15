<?php

declare(strict_types=1);

namespace Acme\Bookings;

final readonly class Booking
{
    private \DateTimeImmutable $start;

    public function __construct(\DateTimeInterface $start, private string $room)
    {
        // readonly is shallow: store an immutable copy, not the caller's object.
        $this->start = \DateTimeImmutable::createFromInterface($start);
    }

    public function start(): \DateTimeImmutable
    {
        return $this->start;
    }

    public function room(): string
    {
        return $this->room;
    }
}
