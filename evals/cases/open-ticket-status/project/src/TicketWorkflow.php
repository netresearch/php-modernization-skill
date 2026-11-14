<?php

declare(strict_types=1);

namespace Cases\OpenTicketStatus;

final class TicketWorkflow
{
    private $statuses;

    /** @param list<string> $extraStatuses */
    public function __construct(array $extraStatuses = [])
    {
        $this->statuses = array_merge(['open', 'closed'], $extraStatuses);
    }

    /** @return list<string> */
    public function statuses(): array
    {
        return $this->statuses;
    }

    public function transition(string $status): string
    {
        if (!in_array($status, $this->statuses, true)) {
            throw new \InvalidArgumentException('Unknown ticket status: ' . $status);
        }
        return $status;
    }
}
