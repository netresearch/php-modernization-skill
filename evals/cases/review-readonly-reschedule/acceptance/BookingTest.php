<?php

declare(strict_types=1);

namespace Cases\ReviewReadonlyReschedule\Tests\Acceptance;

use Cases\ReviewReadonlyReschedule\Booking;
use Cases\ReviewReadonlyReschedule\Guest;
use Cases\ReviewReadonlyReschedule\Rescheduler;
use Cases\ReviewReadonlyReschedule\Room;
use PHPUnit\Framework\TestCase;

final class BookingTest extends TestCase
{
    private function booking(\DateTime $start): Booking
    {
        return new Booking($start, new Room('101', 2), new Guest('Ada', 'ada@example.org'));
    }

    public function testValueObjectsAreReadonly(): void
    {
        foreach ([Booking::class, Room::class, Guest::class] as $class) {
            foreach ((new \ReflectionClass($class))->getProperties() as $property) {
                self::assertTrue($property->isReadOnly(), "{$class}::\${$property->getName()} is not readonly");
            }
        }
    }

    public function testPostponingLeavesTheOriginalBooking(): void
    {
        $booking = $this->booking(new \DateTime('2026-03-01 14:00'));
        $later = (new Rescheduler())->postpone($booking, 2);
        self::assertSame('2026-03-01', $booking->start()->format('Y-m-d'));
        self::assertSame('2026-03-03', $later->start()->format('Y-m-d'));
    }

    public function testChangingThePassedDateDoesNotMoveTheBooking(): void
    {
        $date = new \DateTime('2026-03-01 14:00');
        $booking = $this->booking($date);
        $date->modify('+1 day');
        self::assertSame('2026-03-01', $booking->start()->format('Y-m-d'));
    }

    public function testRoomAndGuest(): void
    {
        $booking = $this->booking(new \DateTime('2026-03-01'));
        self::assertSame('101', $booking->room()->number());
        self::assertSame('Ada', $booking->guest()->name());
    }
}
