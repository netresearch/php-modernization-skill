<?php

declare(strict_types=1);

namespace Cases\MatchUnhandledPayment;

enum PaymentMethod: string
{
    case Card = 'card';
    case Invoice = 'invoice';
    case Paypal = 'paypal';
    case Klarna = 'klarna';
}
