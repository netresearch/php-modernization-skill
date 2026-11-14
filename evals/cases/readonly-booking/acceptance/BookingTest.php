<?php

declare(strict_types=1);

namespace Cases\ReadonlyBooking\Tests\Acceptance;

use Cases\ReadonlyBooking\Booking;
use PHPUnit\Framework\TestCase;

final class BookingTest extends TestCase
{
    public function testPropertiesAreReadonly(): void
    {
        $class = new \ReflectionClass(Booking::class);
        foreach ($class->getProperties() as $property) {
            self::assertTrue($property->isReadOnly(), $property->getName() . ' is not readonly');
        }
    }

    public function testChangingThePassedDateDoesNotChangeTheBooking(): void
    {
        $start = new \DateTime('2026-03-01 10:00');
        $booking = new Booking($start, 'A');
        $start->modify('+1 day');
        self::assertSame('2026-03-01 10:00', $booking->start()->format('Y-m-d H:i'));
    }

    public function testChangingTheReturnedDateDoesNotChangeTheBooking(): void
    {
        $booking = new Booking(new \DateTime('2026-03-01 10:00'), 'A');
        $returned = $booking->start();
        if ($returned instanceof \DateTime) {
            $returned->modify('+1 day');
        }
        self::assertSame('2026-03-01 10:00', $booking->start()->format('Y-m-d H:i'));
        self::assertSame('A', $booking->room());
    }
}
