<?php

declare(strict_types=1);

namespace Acme\Permissions\Tests\Acceptance;

use Acme\Permissions\Permissions;
use PHPUnit\Framework\TestCase;

final class PermissionsTest extends TestCase
{
    public function testRolesInheritDownwards(): void
    {
        $permissions = new Permissions();
        self::assertSame(['manage', 'edit', 'view'], $permissions->for('admin'));
        self::assertSame(['edit', 'view'], $permissions->for('editor'));
        self::assertSame(['view'], $permissions->for('viewer'));
    }

    public function testUnknownRoleIsRejected(): void
    {
        $this->expectException(\InvalidArgumentException::class);
        (new Permissions())->for('guest');
    }
}
