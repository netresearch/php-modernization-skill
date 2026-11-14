<?php

declare(strict_types=1);

namespace Cases\OpenTicketStatus;

final readonly class TicketWorkflow
{
    /** @param list<string> $extraStatuses */
    public function __construct(private array $extraStatuses = [])
    {
    }

    /** @return list<string> */
    public function statuses(): array
    {
        return [
            ...array_map(static fn (TicketStatus $s): string => $s->value, TicketStatus::cases()),
            ...$this->extraStatuses,
        ];
    }

    public function transition(string $status): string
    {
        $known = TicketStatus::tryFrom($status)
            ?? throw new \InvalidArgumentException('Unknown ticket status: ' . $status);

        return $known->value;
    }
}
