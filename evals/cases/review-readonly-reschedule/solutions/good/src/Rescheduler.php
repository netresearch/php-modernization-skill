<?php

declare(strict_types=1);

namespace Acme\Scheduling;

final class Rescheduler
{
    public function postpone(Booking $booking, int $days): Booking
    {
        return new Booking($booking->start()->modify("+{$days} days"), $booking->room(), $booking->guest());
    }
}
