<?php

declare(strict_types=1);

namespace Acme\Scheduling;

final class Rescheduler
{
    public function postpone(Booking $booking, int $days): Booking
    {
        $start = $booking->start();
        $start->modify("+{$days} days");

        return new Booking($start, $booking->room(), $booking->guest());
    }
}
