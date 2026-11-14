<?php

declare(strict_types=1);

namespace Cases\OpenTicketStatus\Tests\Acceptance;

use Cases\OpenTicketStatus\TicketWorkflow;
use PHPUnit\Framework\TestCase;

final class TicketWorkflowTest extends TestCase
{
    public function testBuiltInStatuses(): void
    {
        $workflow = new TicketWorkflow();
        self::assertSame('open', $workflow->transition('open'));
        self::assertSame('closed', $workflow->transition('closed'));
    }

    public function testConfiguredStatusesKeepWorking(): void
    {
        $workflow = new TicketWorkflow(['escalated', 'waiting-for-customer']);
        self::assertSame('escalated', $workflow->transition('escalated'));
        self::assertSame('waiting-for-customer', $workflow->transition('waiting-for-customer'));
        self::assertSame(['open', 'closed', 'escalated', 'waiting-for-customer'], $workflow->statuses());
    }

    public function testUnknownStatusIsRejected(): void
    {
        $this->expectException(\InvalidArgumentException::class);
        (new TicketWorkflow(['escalated']))->transition('bogus');
    }
}
