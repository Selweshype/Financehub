<?php

namespace Database\Seeders;

use App\Models\Category;
use Illuminate\Database\Seeder;

class CategorySeeder extends Seeder
{
    public function run(): void
    {
        $categories = [
            ['name' => 'Food & Dining',  'type' => 'expense', 'icon' => '🍔', 'color' => '#F59E0B'],
            ['name' => 'Transport',      'type' => 'expense', 'icon' => '🚗', 'color' => '#3B82F6'],
            ['name' => 'Housing',        'type' => 'expense', 'icon' => '🏠', 'color' => '#8B5CF6'],
            ['name' => 'Healthcare',     'type' => 'expense', 'icon' => '🏥', 'color' => '#EF4444'],
            ['name' => 'Shopping',       'type' => 'expense', 'icon' => '🛍️', 'color' => '#EC4899'],
            ['name' => 'Entertainment',  'type' => 'expense', 'icon' => '🎬', 'color' => '#06B6D4'],
            ['name' => 'Utilities',      'type' => 'expense', 'icon' => '💡', 'color' => '#F97316'],
            ['name' => 'Education',      'type' => 'expense', 'icon' => '📚', 'color' => '#14B8A6'],
            ['name' => 'Subscriptions',  'type' => 'expense', 'icon' => '📱', 'color' => '#6366F1'],
            ['name' => 'Other Expense',  'type' => 'expense', 'icon' => '💸', 'color' => '#6B7280'],
            ['name' => 'Salary',         'type' => 'income',  'icon' => '💼', 'color' => '#10B981'],
            ['name' => 'Freelance',      'type' => 'income',  'icon' => '💻', 'color' => '#22C55E'],
            ['name' => 'Investment',     'type' => 'income',  'icon' => '📈', 'color' => '#84CC16'],
            ['name' => 'Gift',           'type' => 'income',  'icon' => '🎁', 'color' => '#A78BFA'],
            ['name' => 'Other Income',   'type' => 'income',  'icon' => '💰', 'color' => '#34D399'],
        ];

        foreach ($categories as $cat) {
            Category::firstOrCreate(
                ['name' => $cat['name'], 'user_id' => null, 'type' => $cat['type']],
                array_merge($cat, ['is_default' => true, 'user_id' => null])
            );
        }
    }
}
